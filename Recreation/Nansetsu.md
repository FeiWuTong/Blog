# 何切

记录一下日麻中遇到或想到的何切问题。

## 2020-12-04

不考虑他家情况与dora，以及清一色等高打点的役。

手中已有三个对子（即已有雀头的情况），但缺搭子，目前需要拆一个连对：

**Q1：1133m，拆1m还是3m？**

如果有断幺九的机会，那么切1m是最优的选择，此时能进的张包括23m以及另一个对子。其中进3m可以断幺听牌，进45m可以再打1m彻底转断幺。即使进了2m，如果没有听牌的话将来摸4m也可以打1m转断幺。

不过这里切3m防御力会稍强一些，因为如果场上再多一张3m可以构成1m的薄壁，但反之不行。此外如果摸1m，有跳符的可能性。

**Q2：2233m，拆2m还是3m？**

进张有1234m和对碰。3m有机会成为2m的壁，因此安全度考虑可能是打3m合适。实际上打2m和3m对进张数几乎没有影响（除非牌河已经有1张2m或3m）。

**Q3：2244m，拆2m还是4m？**

因为是跳张连对，所以和2233m还是有一点区别的。区别在于摸5m，445m的形状比335m好很多，所以如果追求更好的牌型进展，不妨打2m，毕竟4m成壁的可能性还是比较小的。

> 总结：进攻的话切边张对牌型有好一些。

这种问题还蛮多，不一定是给出的例子，其他的连对也可，类似的情况。

# 2020-12-07

类似上面问题的前提，这里的问题是：**566m+557s+22p，拆哪个？**

切牌选择一共4种，5m、6m、5s、7s。逐一分析一下就清晰一些：

* 切5m：接下来的进张为6m、2p、5s、6s，一共4种10张，听牌一定是愚形（对碰或者嵌张），显然是最坏的一打。

* 切6m：接下来的进张为4m、7m、2p、5s、6s，一共5种16张，当进张为2p、5s、6s时（共8张）为两面听好型，当进张为4m、7m时听牌可选择对碰或者嵌张的愚形。概率上分布为50%好型/50%愚形听牌。

* 切5s：接下来的进张为4m、6m、7m、2p、6s，一共5种16张，当进张为6s时（共4张）为两面听好型，当进张为4m、6m、7m、2p时听牌只能选择嵌张的愚形。概率上分布为25%好型/75%愚形听牌。

* 切7s：接下来的进张为4m、6m、7m、2p、5s，一共5种14张，当进张为5s、2p时（共4张）为两面听好型，当进张为4m、6m、7m只能听对碰愚形，概率上分布为28.6%好型/71.4%愚形听牌。

> 总结：**提前固定两面搭子，可在保证最大进张面的同时尽可能让听牌成为好型。**

其实可以简单地分析，切5m是将唯一的好型破坏了（好型不管是听牌还是进张都有很大优势）；切5s和7s都是提前固定了嵌张/对碰的愚形搭子，由于固定对碰是会比固定嵌张少2个进张，所以固定对碰会亏一些，而固定嵌张除非进的是嵌张的牌，否则一定是听这个嵌张的愚形，即听愚形的概率大；切5m是提前固定好型搭子，只要进的不是好型的要张，那么就能听好型，即听好型的概率增加不少。

