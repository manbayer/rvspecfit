import glob
import sys
import os
import matplotlib
import argparse
import multiprocessing as mp
import astropy.io.fits as pyfits
import numpy as np
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import astropy.table

sys.path.append('../')
import fitter_ccf
import vel_fit
import spec_fit

import utils

config = utils.read_config()


def procdesi(fname, ofname, fig_prefix):
    """ 
    Process One single file with desi spectra

    Parameters:
    -----------
    fname: str
        The filename with the spectra to be fitted
    ofname: str
        The filename where the table with parameters will be stored
    fig_prefix: str
        The prefix where the figures will be stored
    """
    print ('Processing', fname)
    tab = pyfits.getdata(fname, 'FIBERMAP')
    mws = tab['MWS_TARGET']
    targetid = tab['TARGETID']
    brick_name = tab['BRICKNAME']
    xids = np.nonzero(mws)[0]
    setups = ('b', 'r', 'z')
    fluxes = {}
    ivars = {}
    waves = {}
    for s in setups:
        fluxes[s] = pyfits.getdata(fname, '%s_FLUX' % s.upper())
        ivars[s] = pyfits.getdata(fname, '%s_IVAR' % s.upper())
        waves[s] = pyfits.getdata(fname, '%s_WAVELENGTH' % s.upper())

    outdict = {'brickname': [],
               'target_id': [],
               'vrad': [],
               'vrad_err': [],
               'logg': [],
               'teff': [],
               'vsini': [],
               'feh': [],
               'chisq': []}
    large_error = 1e9
    for curid in xids:
        specdata = []
        curbrick = brick_name[curid]
        curtargetid = targetid[curid]
        for s in setups:
            spec = fluxes[s][curid]
            curivars = ivars[s][curid]
            curivars[curivars <= 0] = 1. / large_error**2
            espec = 1. / curivars**.5
            specdata.append(
                spec_fit.SpecData('desi_%s' % s,
                                  waves[s], spec, espec))
        options = {'npoly': 15}
        res = fitter_ccf.fit(specdata, config)
        paramDict0 = res['best_par']
        fixParam = []
        if res['best_vsini'] is not None:
            paramDict0['vsini'] = res['best_vsini']
        res1 = vel_fit.doit(specdata, paramDict0, fixParam=fixParam,
                            config=config, options=options)
        outdict['brickname'].append(curbrick)
        outdict['target_id'].append(curtargetid)
        outdict['vrad'].append(res1['vel'])
        outdict['vrad_err'].append(res1['vel_err'])
        outdict['logg'].append(res1['param']['logg'])
        outdict['teff'].append(res1['param']['teff'])
        outdict['feh'].append(res1['param']['feh'])
        outdict['chisq'].append(res1['chisq'])
        outdict['vsini'].append(res1['vsini'])
        title = 'logg=%.1f teff=%.1f [Fe/H]=%.1f [alpha/Fe]=%.1f Vrad=%.1f+/-%.1f' % (res1['param']['logg'],
                                                                                      res1['param']['teff'],
                                                                                      res1['param']['feh'],
                                                                                      res1['param']['alpha'],
                                                                                      res1['vel'],
                                                                                      res1['vel_err'])
        plt.clf()
        plt.figure(1, figsize=(6, 6), dpi=300)
        plt.subplot(3, 1, 1)
        plt.plot(specdata[0].lam, specdata[0].spec, 'k-')
        plt.plot(specdata[0].lam, res1['yfit'][0], 'r-')
        plt.title(title)
        plt.subplot(3, 1, 2)
        plt.plot(specdata[1].lam, specdata[1].spec, 'k-')
        plt.plot(specdata[1].lam, res1['yfit'][1], 'r-')
        plt.subplot(3, 1, 3)
        plt.plot(specdata[2].lam, specdata[2].spec, 'k-')
        plt.plot(specdata[2].lam, res1['yfit'][2], 'r-')
        plt.xlabel(r'$\lambda$ [$\AA$]')
        plt.tight_layout()
        plt.savefig(fig_prefix + '_%s_%d.png' % (curbrick, curtargetid))
    outtab = astropy.table.Table(outdict)
    outtab.write(ofname, overwrite=True)


def procdesiWrapper(*args, **kwargs):
    try:
        ret = procdesi(*args, **kwargs)
    except:
        print('failed with these arguments', args, kwargs)
        raise


procdesiWrapper.__doc__ = procdesi.__doc__


def domany(mask, oprefix, fig_prefix, nthreads=1, overwrite=True):
    """
    Process many spectral files

    Parameters:
    -----------
    mask: string
        The filename mask with spectra, i.e path/*fits
    oprefix: string
        The prefix where the table with measurements will be stored
    fig_prefix: string
        The prfix where the figures will be stored
    """
    if nthreads>1:
        parallel = True
    fs = glob.glob(mask)
    if parallel:
        pool = mp.Pool(nthreads)
    res = []
    for f in fs:
        fname = f.split('/')[-1]
        ofname = oprefix + 'outtab_' + fname
        if (not overwrite) and os.path.exists(ofname):
            print('skipping, products already exist', f)
        if parallel:
            res.append(pool.apply_async(procdesi, (f, ofname, fig_prefix)))
        else:
            procdesi(f, ofname, fig_prefix)
    if parallel:
        for r in res:
            r.get()
        pool.close()
        pool.join()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mask',
                        help='mask files to be fitted, i.e. /tmp/desi*fits',
                        type=str)
    parser.add_argument('oprefix',
                        help='Output prefix for the tables',
                        type=str)
    parser.add_argument('fig_prefix',
                        help='Prefix for the fit figures',
                        type=str)
    parser.add_argument('--nthreads',type=int, default=1)
    parser.add_argument('--overwrite', action='store_true', default=False)
    
    args = parser.parse_args()
    mask = args.mask
    oprefix = args.oprefix
    fig_prefix = args.fig_prefix
    nthreads = args.nthreads
    domany(mask, oprefix, fig_prefix, nthreads=nthreads,
           overwrite=args.overwrite)
    #../../desi/dc17a2/spectra-64/1/134/spectra-64-134.fits
