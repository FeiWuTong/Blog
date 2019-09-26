import matplotlib.pyplot as plt
import numpy as np

class Draw:
    def __init__(self, index = 1):
        self.index = index
        self.plot = plt.subplot(111)
        self.length = 0
        self.data = []
        self.filename = ''
        self.datalimit = 100000

    def set_fn(self, fn):
        self.filename = fn

    def read_data(self):
        with open(self.filename, 'r') as f:
            self.length = 0
            self.data = []
            for content in f.readlines():
                self.data.append(content)
                self.length += 1

    def read_data_with_limit(self):
        with open(self.filename, 'r') as f:
            current = 0
            for line in f:
                if current == self.datalimit:
                    current = 0
                    self.draw_scatter()
                    self.update_index()
                    self.length = 0
                    self.data = []
                else:
                    self.data.append(line)
                    self.length += 1
                    current += 1
            if self.data:
                self.draw_scatter()
                self.update_index()
                self.length = 0
                self.data = []
                    

    def update_index(self):
        self.index += self.length

    def draw_scatter(self):
        self.plot.scatter(np.arange(self.index, self.index + self.length),
                          self.data, c = 'c', marker = '.')

    def draw_bar(self):
        pass
        
if __name__ == '__main__':
    prefix = 'AmountStatis1'
    d = Draw()
    d.set_fn(prefix)
    d.read_data_with_limit()
    plt.show()
	
