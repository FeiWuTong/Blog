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

上面只是理论分析，接下来在Geth中实际测试一下，在这里会对Geth的源码进行轻微的修改，使其能够直接输出单笔交易的大小。
