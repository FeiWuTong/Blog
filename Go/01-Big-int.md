# Golang中big.Int的范围与占用空间

在Golang的`math`包中有`big.Int`这么一个数据类型。简单来讲这个数据类型也是`int`整型，但其目的是用来做大数运算的。做过ACM或之类的算法题总会遇到大数运算这类问题，究其原因不过是`int`能表示的范围有限（从早期的8位、16位、32位到现在的64位），一旦超过了范围就会溢出，`big.Int`则是golang中解决这个问题的方式。在网上有很多资料关于它的一些基本操作，这里也没必要赘述。在这里想讨论的是它占用空间的问题，这个问题在网络上没有解答，也没有定论，因为大部分人关注的只是如何去用，能解决什么问题，而没去管其本质层面的实现。

## 问题的提出

为什么会想到去分析big.Int占用的空间？最初是以太坊Geth中的源码引出这个问题的。

代码来源：`go-ethereum/core/types/transactions.go`

``` golang
type Transaction struct {
	data txdata
	// caches
	hash atomic.Value
	size atomic.Value
	from atomic.Value
}

type txdata struct {
	AccountNonce uint64          `json:"nonce"    gencodec:"required"`
	Price        *big.Int        `json:"gasPrice" gencodec:"required"`
	GasLimit     uint64          `json:"gas"      gencodec:"required"`
	Recipient    *common.Address `json:"to"       rlp:"nil"` // nil means contract creation
	Amount       *big.Int        `json:"value"    gencodec:"required"`
	Payload      []byte          `json:"input"    gencodec:"required"`

	// Signature values
	V *big.Int `json:"v" gencodec:"required"`
	R *big.Int `json:"r" gencodec:"required"`
	S *big.Int `json:"s" gencodec:"required"`

	// This is only used when marshaling to JSON.
	Hash *common.Hash `json:"hash" rlp:"-"`
}

// ......

func newTransaction(nonce uint64, to *common.Address, amount *big.Int, gasLimit uint64, gasPrice *big.Int, data []byte) *Transaction {
	if len(data) > 0 {
		data = common.CopyBytes(data)
	}
	d := txdata{
		AccountNonce: nonce,
		Recipient:    to,
		Payload:      data,
		Amount:       new(big.Int),
		GasLimit:     gasLimit,
		Price:        new(big.Int),
		V:            new(big.Int),
		R:            new(big.Int),
		S:            new(big.Int),
	}
	if amount != nil {
		d.Amount.Set(amount)
	}
	if gasPrice != nil {
		d.Price.Set(gasPrice)
	}

	return &Transaction{data: d}
}
```

可以看出，在Geth中交易是由一系列字段构成的，每个字段的意思在这里就不做详细说明了。最初是想分析单个交易的大小的，通过查阅资料可以分析出以下结果（注意到虽然声明的是指针，但交易字段仍会占据相应的空间，有着具体的值）：

> AccountNonce(8bytes) + Price(8bytes?) + Amount(8bytes?) + GasLimit(8bytes) + Recipient(20bytes) + V(1bytes) + R(32bytes) + S(32bytes) = 117bytes

上面只是理论分析，接下来在Geth中实际测试一下，在这里会对Geth的源码进行轻微的修改，使其能够直接输出单笔交易的大小。编译修改后的源码并在私链上运行Geth，发起一笔交易后，去查询交易的相关信息：

``` json
{
	"blockHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
	"blockNumber": null,
	"from": "0x8368b044376a087d9e283844aaf2b6b5cefc1734",
	"gas": 90000,
	"gasPrice": "1000000000",
	"hash": "0xb90e6c3520bde3e97b01ed4cc59ef87387d29826fb6e40684c4ebdefbc6f6ec7",
	"input": "0x",
	"nonce": 0,
	"to": "0x63d0f8e729290980f5159dd4319f9e802e015b86",
	"transactionIndex": 0,
	"value": "10000000000000000",
	"v": "0xb3",
	"r": "0x9cc7a1e007b4d3d6544d564c2ea92a5129fb028cbcfc9bdaa8f5e5ac57a33ab6",
	"s": "0x2fdacc98dc36cce71f27764da346918d7da3da5619f5eed3d174ec00ee982eb0",
	"size": 110
}
```

从输出信息可以看出交易结构字段与之前的分析基本一致，`size`为110字节也与计算的结果相近。之所以`size`会比理论计算的结果要小，是因为交易数据构造时会经过**RLP编码**后再进行存储，以及**big.int具体大小**带来的估算误差。

``` golang
// Size returns the true RLP encoded storage size of the transaction, either by
// encoding and returning it, or returning a previsouly cached value.
func (tx *Transaction) Size() common.StorageSize {
	if size := tx.size.Load(); size != nil {
		return size.(common.StorageSize)
	}
	c := writeCounter(0)
	rlp.Encode(&c, &tx.data)
	tx.size.Store(common.StorageSize(c))
	return common.StorageSize(c)
}
```

在这里引用[参考资料2](#参考资料)中的一部分解释说明：

> RLP (递归长度前缀)适用于任意二进制数据数组的编码。是以太坊中数据序列化/反序列化的主要方法，区块、交易等数据结构在网络传输和持久化时会先经过RLP编码后再存储到数据库中。相比json编码，RLP编码占用空间小，几乎没有冗余信息。

对于以太坊Geth中交易数据大小的分析已经基本完成了。现在的问题是，在交易结构中类型为`big.Int`的字段，其占用的空间大小究竟是多少？

## 分析



## 总结


## 参考资料
1. https://www.jianshu.com/p/1ab2c992cbb7 , Go语言big.Int
1. https://www.jianshu.com/p/c13d9218ac55 , 以太坊中的RLP编码
1. http://www.itkeyword.com/doc/0869406760028703x559/golang-overflows-int64 , 解决go - Golang overflows int64
1. https://stackoverflow.com/questions/24757814/golang-convert-byte-array-to-big-int , Golang: Convert byte array to big.Int