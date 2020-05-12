import os
os.environ['OMP_NUM_THREADS'] = '1'
import sys
import astropy.io.fits as pyfits
import numpy as np
import matplotlib.pyplot as plt
from rvspecfit import utils
from rvspecfit import vel_fit
from rvspecfit import spec_fit

from mktemps import getspec
config = utils.read_config('test.yaml')

# read data
lam = np.linspace(4600, 5400, 800)
v0 = np.random.normal(0, 100)
lam1 = lam * (1 + v0 / 3e5)
resol = 1000.
lamcen = 5000
w = lamcen / resol / 2.35

spec0 = getspec(lam1, 5000, 2, 0.2, -1, wresol=w)
espec = spec0 * 0.001
spec = np.random.normal(spec0, espec)
# construct specdata object
specdata = [spec_fit.SpecData('testgrid', lam, spec, espec)]
options = {'npoly': 15}
paramDict0 = {'logg': 2, 'teff': 5000, 'feh': -0, 'alpha': 0.2, 'vsini': 0.1}
fixParam = []  #'vsini']
res = vel_fit.process(specdata,
                      paramDict0,
                      fixParam=fixParam,
                      config=config,
                      options=options)

#res = vel_fit.process(
#    specdata, paramDict0, fixParam=fixParam, config=config, options=options)
print(res['vel'] - v0, res['vel_err'])
if True:
    plt.figure(figsize=(6, 2), dpi=300)
    plt.plot(specdata[0].lam, specdata[0].spec, 'k-')
    plt.plot(specdata[0].lam, res['yfit'][0], 'r-')
    plt.tight_layout()
    plt.savefig('test_fit_fake_grid.png')
