# 交易的验证

简述交易的验证过程，以及区块同步过程中的交易验证。

## TL;DR

在以太坊中，交易的验证分为两块，相互独立。第一块在广播的交易加入交易池时，需要验证其有效性，包括签名、余额和gas等；第二块在同步区块的时候，需要执行区块内所有的交易来验证交易的有效性。

由第二块的验证过程可知，区块的同步是包含两部分时间花销的，一个是取决于带宽的区块下载时间，另一个则是区块内交易的执行与验证时间。只有在区块正确执行与验证后，节点才会将该区块再次广播出去，因此区块的广播过程中存在关键路径(Critical Path)，影响全网的同步时间。目前以太坊平均的出块时间间隔为15秒，区块交易的执行（验证）时间大约为300ms，跨国的延迟从100ms到2s不等，区块大小平均为30-40KB，带宽最差的节点可低至1Mbps（网络比较差的服务器），下载时间约为300ms。所有时间开销相加，快的话足够广播6轮，根据六度空间理论15秒的间隔几乎可以实现全网同步，当然这只是理想的情况与简单的分析。

## 交易池

交易池中涉及的交易验证比较简单，只需要看`core/tx_pool.go`中的两个函数即可。

先看交易加入交易池的函数。节点收到广播的交易后会先检查交易池中是否存在这个交易，然后再验证交易的有效性，确定有效后才会将交易加入交易池的队列。后续则是根据交易来规划交易在交易池中的位置，不在该篇讨论范围内。

``` golang
// add validates a transaction and inserts it into the non-executable queue for later
// pending promotion and execution. If the transaction is a replacement for an already
// pending or queued one, it overwrites the previous transaction if its price is higher.
//
// If a newly added transaction is marked as local, its sending account will be
// whitelisted, preventing any associated transaction from being dropped out of the pool
// due to pricing constraints.
func (pool *TxPool) add(tx *types.Transaction, local bool) (replaced bool, err error) {
	// If the transaction is already known, discard it
	hash := tx.Hash()
	if pool.all.Get(hash) != nil {
		log.Trace("Discarding already known transaction", "hash", hash)
		knownTxMeter.Mark(1)
		return false, ErrAlreadyKnown
	}
	// If the transaction fails basic validation, discard it
	if err := pool.validateTx(tx, local); err != nil {
		log.Trace("Discarding invalid transaction", "hash", hash, "err", err)
		invalidTxMeter.Mark(1)
		return false, err
    }
    ...
```

接着来看一下验证交易的具体过程。主要验证的内容有：1）交易大小是否超过规定大小。2）交易金额的合法性。3）交易的gas是否超过区块上限。4）交易的签名是否合法。5）交易是否是本地交易（本地交易可以开小灶，减少gas的价格也能打包），若不是则需要交易满足该交易池对gas price要求的下限。6）该交易是否是重放交易（该交易的nonce比交易的发起者最后上链的那笔交易的nonce小说明是重放交易，因为nonce是个递增值）。7）账户是否有足够的余额支持该笔交易的执行（转账金额加手续费）。8）交易“基本”的gas是否足够（至少需要这么多gas，但最终gas的消耗一般是比这个值大的）。

``` golang
// validateTx checks whether a transaction is valid according to the consensus
// rules and adheres to some heuristic limits of the local node (price and size).
func (pool *TxPool) validateTx(tx *types.Transaction, local bool) error {
	// Reject transactions over defined size to prevent DOS attacks
	if uint64(tx.Size()) > txMaxSize {
		return ErrOversizedData
	}
	// Transactions can't be negative. This may never happen using RLP decoded
	// transactions but may occur if you create a transaction using the RPC.
	if tx.Value().Sign() < 0 {
		return ErrNegativeValue
	}
	// Ensure the transaction doesn't exceed the current block limit gas.
	if pool.currentMaxGas < tx.Gas() {
		return ErrGasLimit
	}
	// Make sure the transaction is signed properly
	from, err := types.Sender(pool.signer, tx)
	if err != nil {
		return ErrInvalidSender
	}
	// Drop non-local transactions under our own minimal accepted gas price
	local = local || pool.locals.contains(from) // account may be local even if the transaction arrived from the network
	if !local && tx.GasPriceIntCmp(pool.gasPrice) < 0 {
		return ErrUnderpriced
	}
	// Ensure the transaction adheres to nonce ordering
	if pool.currentState.GetNonce(from) > tx.Nonce() {
		return ErrNonceTooLow
	}
	// Transactor should have enough funds to cover the costs
	// cost == V + GP * GL
	if pool.currentState.GetBalance(from).Cmp(tx.Cost()) < 0 {
		return ErrInsufficientFunds
	}
	// Ensure the transaction has more gas than the basic tx fee.
	intrGas, err := IntrinsicGas(tx.Data(), tx.To() == nil, true, pool.istanbul)
	if err != nil {
		return err
	}
	if tx.Gas() < intrGas {
		return ErrIntrinsicGas
	}
	return nil
}
```

## 区块同步

这部分比较复杂，涉及的源码包括`eth/handler.go`、`eth/fetcher/block_fetcher.go`、`core/blockchain.go`、`core/state_processor.go`和`core/state_transition.go`。

流程的开始在`eth/handler.go`中，这也是最复杂的部分。先看handle函数，这是与同步节点交互的处理过程。大部分内容都不用看，只需要关注两点，第一个是对象`pm`，第二个是函数最后的`handleMsg`操作。前者是一个协议管理的数据结构，在后面会提到；后者是处理来自连接peer的消息的过程。

```golang
// handle is the callback invoked to manage the life cycle of an eth peer. When
// this function terminates, the peer is disconnected.
func (pm *ProtocolManager) handle(p *peer) error {
	// Ignore maxPeers if this is a trusted peer
	if pm.peers.Len() >= pm.maxPeers && !p.Peer.Info().Network.Trusted {
		return p2p.DiscTooManyPeers
	}
	p.Log().Debug("Ethereum peer connected", "name", p.Name())

	// Execute the Ethereum handshake
	var (
		genesis = pm.blockchain.Genesis()
		head    = pm.blockchain.CurrentHeader()
		hash    = head.Hash()
		number  = head.Number.Uint64()
		td      = pm.blockchain.GetTd(hash, number)
	)
	forkID := forkid.NewID(pm.blockchain.Config(), pm.blockchain.Genesis().Hash(), pm.blockchain.CurrentHeader().Number.Uint64())
	if err := p.Handshake(pm.networkID, td, hash, genesis.Hash(), forkID, pm.forkFilter); err != nil {
		p.Log().Debug("Ethereum handshake failed", "err", err)
		return err
	}

	// Register the peer locally
	if err := pm.peers.Register(p, pm.removePeer); err != nil {
		p.Log().Error("Ethereum peer registration failed", "err", err)
		return err
	}
	defer pm.removePeer(p.id)

	// Register the peer in the downloader. If the downloader considers it banned, we disconnect
	if err := pm.downloader.RegisterPeer(p.id, p.version, p); err != nil {
		return err
	}
	pm.chainSync.handlePeerEvent(p)

	// Propagate existing transactions. new transactions appearing
	// after this will be sent via broadcasts.
	pm.syncTransactions(p)

	// If we have a trusted CHT, reject all peers below that (avoid fast sync eclipse)
	if pm.checkpointHash != (common.Hash{}) {
		// Request the peer's checkpoint header for chain height/weight validation
		if err := p.RequestHeadersByNumber(pm.checkpointNumber, 1, 0, false); err != nil {
			return err
		}
		// Start a timer to disconnect if the peer doesn't reply in time
		p.syncDrop = time.AfterFunc(syncChallengeTimeout, func() {
			p.Log().Warn("Checkpoint challenge timed out, dropping", "addr", p.RemoteAddr(), "type", p.Name())
			pm.removePeer(p.id)
		})
		// Make sure it's cleaned up if the peer dies off
		defer func() {
			if p.syncDrop != nil {
				p.syncDrop.Stop()
				p.syncDrop = nil
			}
		}()
	}
	// If we have any explicit whitelist block hashes, request them
	for number := range pm.whitelist {
		if err := p.RequestHeadersByNumber(number, 1, 0, false); err != nil {
			return err
		}
	}
	// Handle incoming messages until the connection is torn down
	for {
		if err := pm.handleMsg(p); err != nil {
			p.Log().Debug("Ethereum message handling failed", "err", err)
			return err
		}
	}
}
```

还是在`eth/handler.go`中，`handleMsg`函数非常长，这里给一个简化后的框架。需要关注的部分为`msg.Code == NewBlockHashesMsg`以及`msg.Code == NewBlockMsg`两个case。由于在以太坊中区块的广播存在两种形式，即区块的哈希（为了减少网络中广播的数据量）与完整区块，因此这两部分都是与区块同步有关的。我们关心的交易验证在后者当中。

``` golang
// handleMsg is invoked whenever an inbound message is received from a remote
// peer. The remote connection is torn down upon returning any error.
func (pm *ProtocolManager) handleMsg(p *peer) error {
    msg, err := p.rw.ReadMsg()
    if err != nil {
        return err
    }
    if msg.Size > ProtocolMaxMsgSize {
        return errResp(ErrMsgTooLarge, "%v > %v", msg.Size, ProtocolMaxMsgSize)
    }
    defer msg.Discard()

    switch {
    case msg.Code == StatusMsg: ......
    case msg.Code == GetBlockHeadersMsg: ......
    case msg.Code == BlockHeadersMsg: ......
    case msg.Code == GetBlockBodiesMsg: ......
    case msg.Code == BlockBodiesMsg: ......
    case p.version >= eth63 && msg.Code == GetNodeDataMsg: ......
    case p.version >= eth63 && msg.Code == NodeDataMsg: ......
    case p.version >= eth63 && msg.Code == GetReceiptsMsg: ......
    case p.version >= eth63 && msg.Code == ReceiptsMsg: ......
    case msg.Code == NewBlockHashesMsg: ......
    case msg.Code == NewBlockMsg: ......
    case msg.Code == TxMsg: ......
    default: return errResp(ErrInvalidMsgCode, "%v", msg.Code)
    }
    return nil
}
```

展开来看，这部分会做一些区块的解析和基本验证（sanityCheck），之后再通过blockFetcher来请求下载同步区块（Enqueue）。到这里同步区块的过程已经差不多了解了，更深入的就与交易验证没有关系了，因此我们跳过。重点来看看什么是`pm`和它所包含的`blockFetcher`内有什么。

``` golang
	case msg.Code == NewBlockMsg:
		// Retrieve and decode the propagated block
		var request newBlockData
		if err := msg.Decode(&request); err != nil {
			return errResp(ErrDecode, "%v: %v", msg, err)
		}
		if hash := types.CalcUncleHash(request.Block.Uncles()); hash != request.Block.UncleHash() {
			log.Warn("Propagated block has invalid uncles", "have", hash, "exp", request.Block.UncleHash())
			break // TODO(karalabe): return error eventually, but wait a few releases
		}
		if hash := types.DeriveSha(request.Block.Transactions(), trie.NewStackTrie(nil)); hash != request.Block.TxHash() {
			log.Warn("Propagated block has invalid body", "have", hash, "exp", request.Block.TxHash())
			break // TODO(karalabe): return error eventually, but wait a few releases
		}
		if err := request.sanityCheck(); err != nil {
			return err
		}
		request.Block.ReceivedAt = msg.ReceivedAt
		request.Block.ReceivedFrom = p

		// Mark the peer as owning the block and schedule it for import
		p.MarkBlock(request.Block.Hash())
		pm.blockFetcher.Enqueue(p.id, request.Block)

		// Assuming the block is importable by the peer, but possibly not yet done so,
		// calculate the head hash and TD that the peer truly must have.
		var (
			trueHead = request.Block.ParentHash()
			trueTD   = new(big.Int).Sub(request.TD, request.Block.Difficulty())
		)
		// Update the peer's total difficulty if better than the previous
		if _, td := p.Head(); trueTD.Cmp(td) > 0 {
			p.SetHead(trueHead, trueTD)
			pm.chainSync.handlePeerEvent(p)
		}
```

先给出pm的结构，其中包含了`downloader`和`blockFetcher`。前者是下载区块用到的，后者是同步区块用到的。

``` golang
type ProtocolManager struct {
	networkID  uint64
	forkFilter forkid.Filter // Fork ID filter, constant across the lifetime of the node

	fastSync  uint32 // Flag whether fast sync is enabled (gets disabled if we already have blocks)
	acceptTxs uint32 // Flag whether we're considered synchronised (enables transaction processing)

	checkpointNumber uint64      // Block number for the sync progress validator to cross reference
	checkpointHash   common.Hash // Block hash for the sync progress validator to cross reference

	txpool     txPool
	blockchain *core.BlockChain
	chaindb    ethdb.Database
	maxPeers   int

	downloader   *downloader.Downloader
	blockFetcher *fetcher.BlockFetcher
	txFetcher    *fetcher.TxFetcher
	peers        *peerSet

	eventMux      *event.TypeMux
	txsCh         chan core.NewTxsEvent
	txsSub        event.Subscription
	minedBlockSub *event.TypeMuxSubscription

	whitelist map[uint64]common.Hash

	// channels for fetcher, syncer, txsyncLoop
	txsyncCh chan *txsync
	quitSync chan struct{}

	chainSync *chainSyncer
	wg        sync.WaitGroup
	peerWG    sync.WaitGroup

	// Test fields or hooks
	broadcastTxAnnouncesOnly bool // Testing field, disable transaction propagation
}
```

再往`blockFetcher`内的结构看去，需要找到源码`eth/fetcher/block_fetcher.go`。只需要看其中的`broadcastBlock`和`insertChain`。前者是广播区块所用的函数，后者是将同步得到的区块在本地上链所用的函数。

``` golang
// BlockFetcher is responsible for accumulating block announcements from various peers
// and scheduling them for retrieval.
type BlockFetcher struct {
	light bool // The indicator whether it's a light fetcher or normal one.

	// Various event channels
	notify chan *blockAnnounce
	inject chan *blockOrHeaderInject

	headerFilter chan chan *headerFilterTask
	bodyFilter   chan chan *bodyFilterTask

	done chan common.Hash
	quit chan struct{}

	// Announce states
	announces  map[string]int                   // Per peer blockAnnounce counts to prevent memory exhaustion
	announced  map[common.Hash][]*blockAnnounce // Announced blocks, scheduled for fetching
	fetching   map[common.Hash]*blockAnnounce   // Announced blocks, currently fetching
	fetched    map[common.Hash][]*blockAnnounce // Blocks with headers fetched, scheduled for body retrieval
	completing map[common.Hash]*blockAnnounce   // Blocks with headers, currently body-completing

	// Block cache
	queue  *prque.Prque                         // Queue containing the import operations (block number sorted)
	queues map[string]int                       // Per peer block counts to prevent memory exhaustion
	queued map[common.Hash]*blockOrHeaderInject // Set of already queued blocks (to dedup imports)

	// Callbacks
	getHeader      HeaderRetrievalFn  // Retrieves a header from the local chain
	getBlock       blockRetrievalFn   // Retrieves a block from the local chain
	verifyHeader   headerVerifierFn   // Checks if a block's headers have a valid proof of work
	broadcastBlock blockBroadcasterFn // Broadcasts a block to connected peers
	chainHeight    chainHeightFn      // Retrieves the current chain's height
	insertHeaders  headersInsertFn    // Injects a batch of headers into the chain
	insertChain    chainInsertFn      // Injects a batch of blocks into the chain
	dropPeer       peerDropFn         // Drops a peer for misbehaving

	// Testing hooks
	announceChangeHook func(common.Hash, bool)           // Method to call upon adding or deleting a hash from the blockAnnounce list
	queueChangeHook    func(common.Hash, bool)           // Method to call upon adding or deleting a block from the import queue
	fetchingHook       func([]common.Hash)               // Method to call upon starting a block (eth/61) or header (eth/62) fetch
	completingHook     func([]common.Hash)               // Method to call upon starting a block body fetch (eth/62)
	importedHook       func(*types.Header, *types.Block) // Method to call upon successful header or block import (both eth/61 and eth/62)
}
```

由于生成`blockFetcher`的过程发生在`eth/handler.go`中，我们还得回去找到相应的部分，实际是在`NewProtocolManager`函数中，这里精简出关键的部分。可以发现`downloader`和`inserter`都是在这当中定义的。可以发现`inserter`主要用到了`blockchain`模块中的`InsertChain`函数来完成同步上链操作。

``` golang
// NewProtocolManager returns a new Ethereum sub protocol manager. The Ethereum sub protocol manages peers capable
// with the Ethereum network.
func NewProtocolManager(config *params.ChainConfig, checkpoint *params.TrustedCheckpoint, mode downloader.SyncMode, networkID uint64, mux *event.TypeMux, txpool txPool, engine consensus.Engine, blockchain *core.BlockChain, chaindb ethdb.Database, cacheLimit int, whitelist map[uint64]common.Hash) (*ProtocolManager, error) {
	// Create the protocol manager with the base fields
	manager := &ProtocolManager{
		networkID:  networkID,
		forkFilter: forkid.NewFilter(blockchain),
		eventMux:   mux,
		txpool:     txpool,
		blockchain: blockchain,
		chaindb:    chaindb,
		peers:      newPeerSet(),
		whitelist:  whitelist,
		txsyncCh:   make(chan *txsync),
		quitSync:   make(chan struct{}),
	}

	...
	
	manager.downloader = downloader.New(manager.checkpointNumber, chaindb, stateBloom, manager.eventMux, blockchain, nil, manager.removePeer)

	// Construct the fetcher (short sync)
	validator := func(header *types.Header) error {
		return engine.VerifyHeader(blockchain, header, true)
	}
	heighter := func() uint64 {
		return blockchain.CurrentBlock().NumberU64()
	}
	inserter := func(blocks types.Blocks) (int, error) {
		// If sync hasn't reached the checkpoint yet, deny importing weird blocks.
		//
		// Ideally we would also compare the head block's timestamp and similarly reject
		// the propagated block if the head is too old. Unfortunately there is a corner
		// case when starting new networks, where the genesis might be ancient (0 unix)
		// which would prevent full nodes from accepting it.
		if manager.blockchain.CurrentBlock().NumberU64() < manager.checkpointNumber {
			log.Warn("Unsynced yet, discarded propagated block", "number", blocks[0].Number(), "hash", blocks[0].Hash())
			return 0, nil
		}
		// If fast sync is running, deny importing weird blocks. This is a problematic
		// clause when starting up a new network, because fast-syncing miners might not
		// accept each others' blocks until a restart. Unfortunately we haven't figured
		// out a way yet where nodes can decide unilaterally whether the network is new
		// or not. This should be fixed if we figure out a solution.
		if atomic.LoadUint32(&manager.fastSync) == 1 {
			log.Warn("Fast syncing, discarded propagated block", "number", blocks[0].Number(), "hash", blocks[0].Hash())
			return 0, nil
		}
		n, err := manager.blockchain.InsertChain(blocks)
		if err == nil {
			atomic.StoreUint32(&manager.acceptTxs, 1) // Mark initial sync done on any fetcher import
		}
		return n, err
	}
	manager.blockFetcher = fetcher.NewBlockFetcher(false, nil, blockchain.GetBlockByHash, validator, manager.BroadcastBlock, heighter, nil, inserter, manager.removePeer)

	...
}
```

到`core/blockchain.go`中找到`InsertChain`，发现除了一些基本的检查外，更多的工作是在包内调用函数`insertChain`中。这里给出`insertChian`的关键部分。这里会调用区块链（bc）的执行器（processor）做交易的处理操作，即`Process`函数，并返回执行的结果（包括receipt和err）。如果执行失败会返回error，结束同步。

``` golang
// insertChain is the internal implementation of InsertChain, which assumes that
// 1) chains are contiguous, and 2) The chain mutex is held.
//
// This method is split out so that import batches that require re-injecting
// historical blocks can do so without releasing the lock, which could lead to
// racey behaviour. If a sidechain import is in progress, and the historic state
// is imported, but then new canon-head is added before the actual sidechain
// completes, then the historic state could be pruned again
func (bc *BlockChain) insertChain(chain types.Blocks, verifySeals bool) (int, error) {
	...

		// Process block using the parent state as reference point
		substart := time.Now()
		receipts, logs, usedGas, err := bc.processor.Process(block, statedb, bc.vmConfig)
		if err != nil {
			bc.reportBlock(block, receipts, err)
			atomic.StoreUint32(&followupInterrupt, 1)
			return it.index, err
		}

	...
```

在`core/state_processor.go`找到`Process`函数。执行单个交易的过程在`ApplyTransaction`中，一旦有一个交易执行失败则会结束整个执行过程。

``` golang
// Process processes the state changes according to the Ethereum rules by running
// the transaction messages using the statedb and applying any rewards to both
// the processor (coinbase) and any included uncles.
//
// Process returns the receipts and logs accumulated during the process and
// returns the amount of gas that was used in the process. If any of the
// transactions failed to execute due to insufficient gas it will return an error.
func (p *StateProcessor) Process(block *types.Block, statedb *state.StateDB, cfg vm.Config) (types.Receipts, []*types.Log, uint64, error) {
	var (
		receipts types.Receipts
		usedGas  = new(uint64)
		header   = block.Header()
		allLogs  []*types.Log
		gp       = new(GasPool).AddGas(block.GasLimit())
	)
	// Mutate the block and state according to any hard-fork specs
	if p.config.DAOForkSupport && p.config.DAOForkBlock != nil && p.config.DAOForkBlock.Cmp(block.Number()) == 0 {
		misc.ApplyDAOHardFork(statedb)
	}
	// Iterate over and process the individual transactions
	for i, tx := range block.Transactions() {
		statedb.Prepare(tx.Hash(), block.Hash(), i)
		receipt, err := ApplyTransaction(p.config, p.bc, nil, gp, statedb, header, tx, usedGas, cfg)
		if err != nil {
			return nil, nil, 0, err
		}
		receipts = append(receipts, receipt)
		allLogs = append(allLogs, receipt.Logs...)
	}
	// Finalize the block, applying any consensus engine specific extras (e.g. block rewards)
	p.engine.Finalize(p.bc, header, statedb, block.Transactions(), block.Uncles())

	return receipts, allLogs, *usedGas, nil
}
```

在`ApplyTransaction`中，我们关心的主要流程只有几步：1）提取出交易的消息。2）生成EVM及其上下文，用于后续执行交易。3）调用以太坊虚拟机EVM执行该消息。其中第三步调用了`core/state_transition.go`中的`ApplyMessage`。

``` golang
// ApplyTransaction attempts to apply a transaction to the given state database
// and uses the input parameters for its environment. It returns the receipt
// for the transaction, gas used and an error if the transaction failed,
// indicating the block was invalid.
func ApplyTransaction(config *params.ChainConfig, bc ChainContext, author *common.Address, gp *GasPool, statedb *state.StateDB, header *types.Header, tx *types.Transaction, usedGas *uint64, cfg vm.Config) (*types.Receipt, error) {
	msg, err := tx.AsMessage(types.MakeSigner(config, header.Number))
	if err != nil {
		return nil, err
	}
	// Create a new context to be used in the EVM environment
	context := NewEVMContext(msg, header, bc, author)
	// Create a new environment which holds all relevant information
	// about the transaction and calling mechanisms.
	vmenv := vm.NewEVM(context, statedb, config, cfg)

	if config.IsYoloV2(header.Number) {
		statedb.AddAddressToAccessList(msg.From())
		if dst := msg.To(); dst != nil {
			statedb.AddAddressToAccessList(*dst)
			// If it's a create-tx, the destination will be added inside evm.create
		}
		for _, addr := range vmenv.ActivePrecompiles() {
			statedb.AddAddressToAccessList(addr)
		}
	}

	// Apply the transaction to the current state (included in the env)
	result, err := ApplyMessage(vmenv, msg, gp)
	if err != nil {
		return nil, err
	}
	// Update the state with pending changes
	var root []byte
	if config.IsByzantium(header.Number) {
		statedb.Finalise(true)
	} else {
		root = statedb.IntermediateRoot(config.IsEIP158(header.Number)).Bytes()
	}
	*usedGas += result.UsedGas

	// Create a new receipt for the transaction, storing the intermediate root and gas used by the tx
	// based on the eip phase, we're passing whether the root touch-delete accounts.
	receipt := types.NewReceipt(root, result.Failed(), *usedGas)
	receipt.TxHash = tx.Hash()
	receipt.GasUsed = result.UsedGas
	// if the transaction created a contract, store the creation address in the receipt.
	if msg.To() == nil {
		receipt.ContractAddress = crypto.CreateAddress(vmenv.Context.Origin, tx.Nonce())
	}
	// Set the receipt logs and create a bloom for filtering
	receipt.Logs = statedb.GetLogs(tx.Hash())
	receipt.Bloom = types.CreateBloom(types.Receipts{receipt})
	receipt.BlockHash = statedb.BlockHash()
	receipt.BlockNumber = header.Number
	receipt.TransactionIndex = uint(statedb.TxIndex())

	return receipt, err
}
```

来到`core/state_transition.go`的`ApplyMessage`中，发现其调用的是函数`TransitionDb`。

``` golang
// ApplyMessage computes the new state by applying the given message
// against the old state within the environment.
//
// ApplyMessage returns the bytes returned by any EVM execution (if it took place),
// the gas used (which includes gas refunds) and an error if it failed. An error always
// indicates a core error meaning that the message would always fail for that particular
// state and would never be accepted within a block.
func ApplyMessage(evm *vm.EVM, msg Message, gp *GasPool) (*ExecutionResult, error) {
	return NewStateTransition(evm, msg, gp).TransitionDb()
}
```

进到`TransitionDb`后就能发现这部分其实就是真正交易执行与验证的函数块了。这里会检查环境和交易的一系列参数，并验证交易，通过后会调用EVM的`Call`函数在虚拟机内执行这笔交易，最后统计交易所消耗的gas，并计算返还的gas。

``` golang
// TransitionDb will transition the state by applying the current message and
// returning the evm execution result with following fields.
//
// - used gas:
//      total gas used (including gas being refunded)
// - returndata:
//      the returned data from evm
// - concrete execution error:
//      various **EVM** error which aborts the execution,
//      e.g. ErrOutOfGas, ErrExecutionReverted
//
// However if any consensus issue encountered, return the error directly with
// nil evm execution result.
func (st *StateTransition) TransitionDb() (*ExecutionResult, error) {
	// First check this message satisfies all consensus rules before
	// applying the message. The rules include these clauses
	//
	// 1. the nonce of the message caller is correct
	// 2. caller has enough balance to cover transaction fee(gaslimit * gasprice)
	// 3. the amount of gas required is available in the block
	// 4. the purchased gas is enough to cover intrinsic usage
	// 5. there is no overflow when calculating intrinsic gas
	// 6. caller has enough balance to cover asset transfer for **topmost** call

	// Check clauses 1-3, buy gas if everything is correct
	if err := st.preCheck(); err != nil {
		return nil, err
	}
	msg := st.msg
	sender := vm.AccountRef(msg.From())
	homestead := st.evm.ChainConfig().IsHomestead(st.evm.BlockNumber)
	istanbul := st.evm.ChainConfig().IsIstanbul(st.evm.BlockNumber)
	contractCreation := msg.To() == nil

	// Check clauses 4-5, subtract intrinsic gas if everything is correct
	gas, err := IntrinsicGas(st.data, contractCreation, homestead, istanbul)
	if err != nil {
		return nil, err
	}
	if st.gas < gas {
		return nil, ErrIntrinsicGas
	}
	st.gas -= gas

	// Check clause 6
	if msg.Value().Sign() > 0 && !st.evm.CanTransfer(st.state, msg.From(), msg.Value()) {
		return nil, ErrInsufficientFundsForTransfer
	}
	var (
		ret   []byte
		vmerr error // vm errors do not effect consensus and are therefore not assigned to err
	)
	if contractCreation {
		ret, _, st.gas, vmerr = st.evm.Create(sender, st.data, st.gas, st.value)
	} else {
		// Increment the nonce for the next transaction
		st.state.SetNonce(msg.From(), st.state.GetNonce(sender.Address())+1)
		ret, st.gas, vmerr = st.evm.Call(sender, st.to(), st.data, st.gas, st.value)
	}
	st.refundGas()
	st.state.AddBalance(st.evm.Coinbase, new(big.Int).Mul(new(big.Int).SetUint64(st.gasUsed()), st.gasPrice))

	return &ExecutionResult{
		UsedGas:    st.gasUsed(),
		Err:        vmerr,
		ReturnData: ret,
	}, nil
}
```

到这里区块同步过程中的交易验证就结束了。不过我们可以看一下交易验证完后，会发生什么。回到`eth/fetcher/block_fetcher`中，其中的`loop`是fetcher的主要循环流程，其中包括了导入区块的函数`importBlocks`（其中轻节点则是导入区块头）。

``` golang
// Loop is the main fetcher loop, checking and processing various notification
// events.
func (f *BlockFetcher) loop() {
	...
		for !f.queue.Empty() {
			op := f.queue.PopItem().(*blockOrHeaderInject)
			hash := op.hash()
			if f.queueChangeHook != nil {
				f.queueChangeHook(hash, false)
			}
			// If too high up the chain or phase, continue later
			number := op.number()
			if number > height+1 {
				f.queue.Push(op, -int64(number))
				if f.queueChangeHook != nil {
					f.queueChangeHook(hash, true)
				}
				break
			}
			// Otherwise if fresh and still unknown, try and import
			if (number+maxUncleDist < height) || (f.light && f.getHeader(hash) != nil) || (!f.light && f.getBlock(hash) != nil) {
				f.forgetBlock(hash)
				continue
			}
			if f.light {
				f.importHeaders(op.origin, op.header)
			} else {
				f.importBlocks(op.origin, op.block)
			}
		}
	...
```

在`importBlocks`中也包含了`insertChain`函数（这个就是之前提到的，在`eth/handler`的`NewProtocolManager`中定义的inserter），调用流程之前也有提到。在import完成之后，才会异步地继续广播该区块。注意到`broadcastBlock`函数中，第二个参数`true`代表广播的是完整区块，`false`代表广播的是区块的哈希。在验证完区块头后，会将完整的区块广播给部分peer节点。在执行完区块的本地上链后会将区块的哈希再一次广播给剩余peer节点，宣布该区块确实加入了本地的区块链（announce its availability）。（这里的peer指的是没有该区块hash的节点，已经同步该区块的节点则不会被广播）

``` golang
// importBlocks spawns a new goroutine to run a block insertion into the chain. If the
// block's number is at the same height as the current import phase, it updates
// the phase states accordingly.
func (f *BlockFetcher) importBlocks(peer string, block *types.Block) {
	hash := block.Hash()

	// Run the import on a new thread
	log.Debug("Importing propagated block", "peer", peer, "number", block.Number(), "hash", hash)
	go func() {
		defer func() { f.done <- hash }()

		// If the parent's unknown, abort insertion
		parent := f.getBlock(block.ParentHash())
		if parent == nil {
			log.Debug("Unknown parent of propagated block", "peer", peer, "number", block.Number(), "hash", hash, "parent", block.ParentHash())
			return
		}
		// Quickly validate the header and propagate the block if it passes
		switch err := f.verifyHeader(block.Header()); err {
		case nil:
			// All ok, quickly propagate to our peers
			blockBroadcastOutTimer.UpdateSince(block.ReceivedAt)
			go f.broadcastBlock(block, true)

		case consensus.ErrFutureBlock:
			// Weird future block, don't fail, but neither propagate

		default:
			// Something went very wrong, drop the peer
			log.Debug("Propagated block verification failed", "peer", peer, "number", block.Number(), "hash", hash, "err", err)
			f.dropPeer(peer)
			return
		}
		// Run the actual import and log any issues
		if _, err := f.insertChain(types.Blocks{block}); err != nil {
			log.Debug("Propagated block import failed", "peer", peer, "number", block.Number(), "hash", hash, "err", err)
			return
		}
		// If import succeeded, broadcast the block
		blockAnnounceOutTimer.UpdateSince(block.ReceivedAt)
		go f.broadcastBlock(block, false)

		// Invoke the testing hook if needed
		if f.importedHook != nil {
			f.importedHook(nil, block)
		}
	}()
}
```

（`eth/handler.go`中的`BroadcastBlock`函数）

``` golang
// BroadcastBlock will either propagate a block to a subset of its peers, or
// will only announce its availability (depending what's requested).
func (pm *ProtocolManager) BroadcastBlock(block *types.Block, propagate bool) {
	hash := block.Hash()
	peers := pm.peers.PeersWithoutBlock(hash)

	// If propagation is requested, send to a subset of the peer
	if propagate {
		// Calculate the TD of the block (it's not imported yet, so block.Td is not valid)
		var td *big.Int
		if parent := pm.blockchain.GetBlock(block.ParentHash(), block.NumberU64()-1); parent != nil {
			td = new(big.Int).Add(block.Difficulty(), pm.blockchain.GetTd(block.ParentHash(), block.NumberU64()-1))
		} else {
			log.Error("Propagating dangling block", "number", block.Number(), "hash", hash)
			return
		}
		// Send the block to a subset of our peers
		transfer := peers[:int(math.Sqrt(float64(len(peers))))]
		for _, peer := range transfer {
			peer.AsyncSendNewBlock(block, td)
		}
		log.Trace("Propagated block", "hash", hash, "recipients", len(transfer), "duration", common.PrettyDuration(time.Since(block.ReceivedAt)))
		return
	}
	// Otherwise if the block is indeed in out own chain, announce it
	if pm.blockchain.HasBlock(hash, block.NumberU64()) {
		for _, peer := range peers {
			peer.AsyncSendNewBlockHash(block)
		}
		log.Trace("Announced block", "hash", hash, "recipients", len(peers), "duration", common.PrettyDuration(time.Since(block.ReceivedAt)))
	}
}
```

事实上，只有区块内所有的交易验证完后才会将该区块广播给所有的peer节点，否则根据上面的`BroadcastBlock`函数，收到广播区块的节点只会是根号级别的。在验证完后会将区块哈希发给剩余节点，剩余的节点再请求获取完整的区块。

在以太坊的[白皮书](https://ethereum.org/en/whitepaper/#fees)中也有提到这个过程，这里引用一下：

> However, there are several important deviations from those assumptions in reality:
> 
> 1. The miner does pay a higher cost to process the transaction than the other verifying nodes, **since the extra verification time delays block propagation and thus increases the chance the block will become a stale.**

## 题外话

比较令我好奇的是区块同步这块的交易验证与交易池里的交易验证是没有关联，相互独立的。这样验证交易签名的时候会存在额外的开销，即交易在进交易池时已经验证过了一次交易的签名，如果在同步区块的过程中发现区块的交易有部分是存在于交易池中的，那么相当于这笔交易的签名被验证了两次。为了减少同步区块时验证ECDSA签名的时间开销，比特币是会检查交易池中是否存在这笔交易，如果存在则跳过这部分检查过程，以加快验证的速度，具体参考比特币的[Pull#1349](https://github.com/bitcoin/bitcoin/pull/1349)。以太坊之所以不采用这个方式，我猜测最大的可能是因为以太坊交易的执行需要通过EVM，而交易签名的验证相比于EVM执行的时间较短，因此以太坊不太关心这一小部分交易验证的优化。