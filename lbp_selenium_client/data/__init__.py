import lzma
from os.path import abspath, dirname, join

import numpy as np

data_folder = dirname(abspath(__file__))

with lzma.open(join(data_folder,"buttons.npy.xz")) as fp:
    buttons = np.load(fp)
