# 大数据下的Plot绘制

Python数据的可视化、图表的绘制，经常会用到matplotlib库，相关的介绍、源码和教学数不胜数，这里不再赘述。

用到该库的起因是Kimono君提取了一大批数据，现在需要对这些数据进行可视化处理，用图的形式将数据展示出来以方便后续的分析。由于Python有很成熟的绘制图表的库matplotlib，且其绘图脚本编写起来代码量少，效率高，因此kimono君便打算用python来给这批数据作图。

这批数据的量比较大，有大约1.5GB，目前分割成了10个文件。如果只是简单的绘图，python可以很轻易地完成这项工作，事实上也有很多相关的教学资源和笔记可以参考。但对于大数据下Plot的绘制，就需要思考内存的问题了，目前在网上也没怎么看到相关的介绍。

## 概况

- 输入： 测试用的190M数据文件，每行一个unsigned int，共约1400万行。
- 输出： 绘制数据的散点分布
- 环境： Python3.60，主要库为numpy和matplotlib.plt

## 过程与结果

首先将绘图代码的框架大致写一下：

```python
import matplotlib.pyplot as plt
import numpy as np

class Draw:
    def __init__(self, index = 1):
        pass

    def set_fn(self, fn):
        pass

    def read_data(self):
        pass

    def draw_scatter(self):
        pass

    def draw_bar(self):
        pass
        
if __name__ == '__main__':
	pass
```

这里为*Draw*类额外加了两个参数`index`和`fn`。`fn`是为了读取多个文件设置的文件名参数，`index`最初仅仅是作为数据的序号（横坐标）引入的一个参数。

将代码填入框架中，用两个删减后的数据文件进行简单的功能测试（每个大约1M，7万行）。这里`index`可以通过调用`update_index`来完成多个文件的连续绘图。

```python
class Draw:
	def __init__(self, index = 1):
        self.index = index
        self.plot = plt.subplot(111)
        self.length = 0
        self.data = []
        self.filename = ''

    def set_fn(self, fn):
        self.filename = fn

    def read_data(self):
        with open(self.filename, 'r') as f:
            self.length = 0
            self.data = []
            for content in f.readlines():
                self.data.append(content)
                self.length += 1
                    
    def update_index(self):
        self.index += self.length

    def draw_scatter(self):
        self.plot.scatter(np.arange(self.index, self.index + self.length),
                          self.data, c = 'c', marker = '.')

if __name__ == '__main__':
	prefix = 'datafile'
	d = Draw()
	for i in range(1, 3):
		d.set_fn(prefix + str(i))
		d.read_data()
	    d.draw_scatter()
	    d.update_index()
	plt.show()
```

结果：

## 参考资料

1. [Python数据可视化—matplotlib笔记](https://blog.csdn.net/qq_34264472/article/details/53814635)
1. [python 大文件以行为单位读取方式比对](https://www.cnblogs.com/aicro/p/3371986.html)