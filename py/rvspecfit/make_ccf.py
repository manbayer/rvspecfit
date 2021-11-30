from __future__ import print_function
import pickle
import argparse
import multiprocessing as mp
import numpy as np
import scipy.interpolate
import scipy.stats
import sys
import logging

from rvspecfit import spec_fit
from rvspecfit import make_interpol
import rvspecfit

git_rev = rvspecfit.__version__

CCF_PKL_NAME = 'ccf_%s.pkl'
CCF_DAT_NAME = 'ccfdat_%s.npz'
CCF_MOD_NAME = 'ccfmod_%s.npy'


class CCFConfig:
    """ Configuration class for cross-correlation functions """
    def __init__(self,
                 logl0=None,
                 logl1=None,
                 npoints=None,
                 splinestep=1000,
                 maxcontpts=20):
        """
        Configure the cross-correlation

        Parameters
        ----------
        logl0: float
            The natural logarithm of the wavelength of the beginning of
            the CCF
        logl1: float
            The natural logarithm of the wavelength of the end of the CCF
        npoints: integer
            The number of points in the cross correlation functions
        splinestep: float, optional
            The stepsize in km/s that determines the smoothness of the
            continuum fit
        maxcontpts: integer, optional
             The maximum number of points used for the continuum fit
        """

        self.logl0 = logl0
        self.logl1 = logl1
        self.npoints = npoints
        self.maxcontpts = maxcontpts
        self.splinestep = max(
            splinestep, 3e5 * (np.exp((logl1 - logl0) / self.maxcontpts) - 1))


def get_continuum(lam0, spec0, espec0, ccfconf=None, bin=11):
    """Determine the continuum of the spectrum by fitting a spline

    Parameters
    ----------

    lam0: numpy array
        The wavelength vector
    spec0: numpy array
        The spectral vector
    espec0: numpy array
        The vector of spectral uncertainties
    ccfconf: CCFConfig object
        The CCF configuration object
    bin: integer, optional
        The input spectrum will be binned by median filter by this number
        before the fit

    Returns
    -------
    cont: numpy array
        The continuum vector

"""

    lammin = lam0.min()
    N = np.log(lam0.max() / lammin) / np.log(1 + ccfconf.splinestep / 3e5)
    N = int(np.ceil(N))
    # Determine the nodes of the spline used for the continuum fit
    nodes = lammin * np.exp(
        np.arange(N) * np.log(1 + ccfconf.splinestep / 3e5))
    nodesedges = lammin * np.exp(
        (-0.5 + np.arange(N + 1)) * np.log(1 + ccfconf.splinestep / 3e5))
    medspec = np.median(spec0)
    if medspec <= 0:
        medspec = np.abs(medspec)
        if medspec == 0:
            medspec = 1
        logging.warning('The spectrum has a median that is non-positive...')

    BS = scipy.stats.binned_statistic(lam0, spec0, 'median', bins=nodesedges)
    p0 = np.log(np.maximum(BS.statistic, 1e-3 * medspec))
    p0[~np.isfinite(p0)] = np.log(medspec)

    ret = scipy.optimize.least_squares(fit_resid,
                                       p0,
                                       loss='soft_l1',
                                       args=((nodes, lam0, spec0, espec0),
                                             False))
    cont = fit_resid(ret['x'], (nodes, lam0, spec0, espec0), True)
    return cont


def fit_resid(p, args=None, getModel=False):
    # residual of the fit for the fitting
    nodes, lam, spec, espec = args
    mod = np.exp(
        np.clip(
            scipy.interpolate.UnivariateSpline(nodes, p, s=0, k=2)(lam), -100,
            100))
    if getModel:
        return mod
    return (mod - spec) / espec


def apodize(spec):
    """
    Apodize the spectrum

    Parameters
    -----------
    spec: numpy array
        The input numpy array
    """
    frac = 0.15
    lspec = len(spec)
    x = np.arange(lspec) * 1.
    mask = 1 + 0 * x
    ind = x < (frac * lspec)
    mask[ind] = (1 - np.cos(x[ind] / frac / lspec * np.pi)) * .5
    ind = (x - lspec + 1) > (-frac * lspec)
    mask[ind] = (1 - np.cos((lspec - x - 1)[ind] / frac / lspec * np.pi)) * .5
    return mask * spec


def pad(x, y):
    """
    Pad the input array to the power of two lengths

    Parameters
    -----------
    x: numpy array
        wavelength vector
    y: numpy array
        spectrum

    Returns
    --------
    x2: numpy array
        New wavelength vector
    y2: numpy array
        New spectrum vector
    """
    lspec = len(y)
    l1 = int(2**np.ceil(np.log(lspec) / np.log(2)))
    delta1 = int((l1 - lspec) / 2)  # extra pixels on the left
    delta2 = int((l1 - lspec) - delta1)  # extra pixels on the right
    y2 = np.concatenate((np.zeros(delta1), y, np.zeros(delta2)))
    deltax = x[1] - x[0]
    if np.allclose(np.diff(x), deltax):
        x2 = np.concatenate((np.arange(-delta1, 0) * deltax + x[0], x,
                             x[-1] + deltax * (1 + np.arange(delta2))))
    elif np.allclose(np.diff(np.log(x)), np.log(x[1] / x[0])):

        x2 = np.concatenate(deltax**(np.arange(-delta1, 0) * x[0], x,
                                     x[-1] * deltax**(1 + np.arange(delta2))))
    else:
        raise Exception(
            'the wavelength axis is neither logarithmic, nor linear')
    return x2, y2


def preprocess_model(logl,
                     lammodel,
                     model0,
                     vsini=None,
                     ccfconf=None,
                     modid=None):
    """
    Take the input template model and return prepared for FFT vectors.
    That includes padding, apodizing and normalizing by continuum

    Parameters
    -----------
    logl: numpy array
        The array of log wavelengths on which we want to outputted spectra
    lammodel: numpy array
        The wavelength array of the model
    model0: numpy array
        The initial model spectrum
    vsini: float, optional
        The stellar rotation, vsini
    ccfconf: CCFConfig object, required
        The CCF configuration object

    Returns
    --------

    xlogl: Numpy array
        The log-wavelength of the resulting processed model0
    cpa_model: Numpy array
        The continuum normalized/subtracted, apodized and padded spectrum
    """
    if vsini is not None and vsini != 0:
        m = spec_fit.convolve_vsini(lammodel, model0, vsini)
    else:
        m = model0
    cont = get_continuum(lammodel,
                         m,
                         np.maximum(m * 1e-5, 1e-2 * np.median(m)),
                         ccfconf=ccfconf)

    cont = np.maximum(cont, 1e-2 * np.median(cont))
    c_model = scipy.interpolate.interp1d(np.log(lammodel), m / cont)(logl)
    return c_model


def preprocess_model_list(lammodels, models, params, ccfconf, vsinis=None):
    """Apply preprocessing to the array of models

    Parameters
    ----------

    lammodels: numpy array
        The array of wavelengths of the models
        (assumed to be the same for all models)
    models: numpy array
        The 2D array of modell with the shape [number_of_models, len_of_model]
    params: numpy array
        The 2D array of template parameters (i.e. stellar atmospheric
        parameters) with the shape
        [number_of_models,length_of_parameter_vector]
    ccfconf: CCFConfig object
        CCF configuration
    vsinis: list of floats
        The list of possible Vsini values to convolve model spectra with
        Could be None

    Returns
    -------
    ret: tuple
         **FILL/CHECK ME**
         1) log wavelenghts
         2) processed spectra,
         3) spectral params
         4) list of vsini
    """
    nthreads = 16
    logl = np.linspace(ccfconf.logl0, ccfconf.logl1, ccfconf.npoints)
    res = []
    retparams = []
    if vsinis is None:
        vsinis = [None]
    vsinisList = []
    pool = mp.Pool(nthreads)
    q = []
    for imodel, m0 in enumerate(models):
        for vsini in vsinis:
            retparams.append(params[imodel])
            q.append(
                pool.apply_async(
                    preprocess_model,
                    (logl, lammodels, m0, vsini, ccfconf, params[imodel])))
            vsinisList.append(vsini)

    for ii, curx in enumerate(q):
        print('Processing : %d / %d' % (ii, len(q)))
        c_model = curx.get()
        res.append(c_model)
    pool.close()
    pool.join()
    res = np.array(res)
    return res, retparams, vsinisList


def interp_masker(lam, spec, badmask):
    """
    Fill the gaps spectrum by interpolating across a badmask.
    The gaps are filled by linear interpolation. The edges are just
    using the value of the closest valid pixel.

    Parameters
    -----------
    lam: numpy array
        The array of wavelengths of pixels
    spec: numpy array
        The spectrum array
    badmask: boolean array
        The array identifying bad pixels

    Returns
    --------
    spec: numpy array
        The array with bad pixels interpolated away

    """
    spec1 = spec * 1
    xbad = np.nonzero(badmask)[0]
    xgood = np.nonzero(~badmask)[0]
    if len(xgood) == 0:
        logging.warning('All the pixels are masked for the ccf determination')
        ret = spec1
        ret[~np.isfinite(ret)] = 1
        return ret
    xpos = np.searchsorted(xgood, xbad)
    leftedge = xpos == 0
    rightedge = xpos == len(xgood)
    mid = (~leftedge) & (~rightedge)
    l1, l2 = lam[xgood[xpos[mid] - 1]], lam[xgood[xpos[mid]]]
    s1, s2 = spec[xgood[xpos[mid] - 1]], spec[xgood[xpos[mid]]]
    l0 = lam[xbad[mid]]
    spec1[xbad[leftedge]] = spec[xgood[0]]
    spec1[xbad[rightedge]] = spec[xgood[-1]]
    spec1[xbad[mid]] = (-(l1 - l0) * s2 + (l2 - l0) * s1) / (l2 - l1)
    return spec1


def preprocess_data(lam, spec0, espec, ccfconf=None, badmask=None, maxerr=10):
    """
    Preprocess data in the same manner as the template spectra, normalize by
    the continuum, apodize and pad

    Parameters
    -----------
    lam: numpy array
        The wavelength vector
    spec0: numpy array
        The input spectrum vector
    espec0: numpy array
        The error-vector of the spectrum
    ccfconf: CCFConfig object
        The CCF configuration
    badmask: Numpy array(boolean), optional
        The optional mask for the CCF
    maxerr: integer
        The maximum value of error to be masked in units of median(error)
    Returns
    cap_spec: numpy array
        The processed apodized/normalized/padded spectrum

    """
    ccf_logl = np.linspace(ccfconf.logl0, ccfconf.logl1, ccfconf.npoints)
    ccf_lam = np.exp(ccf_logl)
    # to modify them
    curespec = espec.copy()
    curspec = spec0.copy()
    if badmask is None:
        badmask = np.zeros(len(curespec), dtype=bool)
    mederr = np.nanmedian(curespec)
    badmask = badmask | (curespec > maxerr * mederr)
    curespec[badmask] = 1e9 * mederr
    curspec = interp_masker(lam, curspec, badmask)
    # not really needed but may be helpful for continuun determination
    cont = get_continuum(lam, curspec, curespec, ccfconf=ccfconf)
    curivar = 1. / curespec**2
    curivar[badmask] = 0
    medv = np.median(curspec)
    if medv > 0:
        cont = np.maximum(1e-2 * medv, cont)
    else:
        cont = np.maximum(cont, 1)

    # normalize the spectrum by continuum and update ivar
    c_spec = spec0 / cont
    curivar = cont**2 * curivar

    c_spec[badmask] = 0
    xind = np.searchsorted(lam, ccf_lam) - 1
    indsub = (xind >= 0) & (xind <= (len(lam) - 2))
    # these are the pixels we can fill
    res1 = np.zeros(len(ccf_logl))
    res2 = np.zeros(len(ccf_logl))
    left_i = xind[indsub]
    right_i = left_i + 1
    right_w = (ccf_lam[indsub] - lam[left_i]) / (lam[right_i] - lam[left_i])
    left_w = 1 - right_w
    res1[indsub] = left_w * c_spec[left_i] + right_w * c_spec[right_i]
    left_ivar = curivar[left_i]
    right_ivar = curivar[right_i]

    # prevent division by zero
    res2[indsub] = left_ivar * right_ivar / (
        left_w**2 * right_ivar + right_w**2 * left_ivar +
        ((left_ivar * right_ivar) == 0).astype(int))

    return res1, res2


def ccf_executor(spec_setup,
                 ccfconf,
                 prefix=None,
                 oprefix=None,
                 every=10,
                 vsinis=None,
                 revision=''):
    """
    Prepare the FFT transformations for the CCF

    Parameters
    -----------
    spec_setup: string
        The name of the spectroscopic spec_setup
    ccfconf: CCFConfig
        The CCF configuration object
    prefix: string
        The input directory where the templates are located
    oprefix: string
        The output directory
    every: integer (optional)
        Produce FFTs of every N-th spectrum
    vsinis: list (optional)
        Produce FFTS of the templates  with Vsini from the list.
        Could be None (it means no rotation will be added)
    revision: str (optional)
        The revision of the files/run that will be tagged in the pickle file

    Returns
    -------
    Nothing

    """

    with open(('%s/' + make_interpol.SPEC_PKL_NAME) % (prefix, spec_setup),
              'rb') as fp:
        D = pickle.load(fp)
        vec, specs, lam, parnames = D['vec'], D['specs'], D['lam'], D[
            'parnames']
        del D

    nspec = specs.shape[0]
    rng = np.random.Generator(np.random.PCG64(44))
    inds = rng.permutation(np.arange(nspec))[:(nspec // every)]
    specs = specs[inds, :]
    vec = vec.T[inds, :]
    nspec, lenspec = specs.shape

    models, params, vsinis = preprocess_model_list(lam,
                                                   np.exp(specs),
                                                   vec,
                                                   ccfconf,
                                                   vsinis=vsinis)
    ffts = np.array([np.fft.fft(x) for x in models])
    fft2s = np.array([np.fft.fft(x**2) for x in models])
    savefile = ('%s/' + CCF_PKL_NAME) % (oprefix, spec_setup)
    datsavefile = ('%s/' + CCF_DAT_NAME) % (oprefix, spec_setup)
    modsavefile = ('%s/' + CCF_MOD_NAME) % (oprefix, spec_setup)
    dHash = {}
    dHash['params'] = params
    dHash['ccfconf'] = ccfconf
    dHash['vsinis'] = vsinis
    dHash['parnames'] = parnames
    dHash['revision'] = revision

    with open(savefile, 'wb') as fp:
        pickle.dump(dHash, fp)
    np.savez(datsavefile, fft=np.array(ffts), fft2=np.array(fft2s))
    np.save(modsavefile, np.array(models))


def main(args):
    parser = argparse.ArgumentParser(
        description='Create the Fourier transformed templates')
    parser.add_argument('--prefix',
                        type=str,
                        help='Location of the input spectra')
    parser.add_argument(
        '--oprefix',
        type=str,
        default='templ_data/',
        help='Location where the ouput products will be located')
    parser.add_argument('--setup',
                        type=str,
                        help='Name of spectral configuration')
    parser.add_argument('--lambda0',
                        type=float,
                        help='Starting wavelength in Angstroms',
                        required=True)
    parser.add_argument('--lambda1',
                        type=float,
                        help='Wavelength endpoint',
                        required=True)
    parser.add_argument('--step',
                        type=float,
                        help='Pixel size in angstroms',
                        required=True)
    parser.add_argument('--revision',
                        type=str,
                        help='Revision of the data files/run',
                        required=False,
                        default='')
    parser.add_argument(
        '--vsinis',
        type=str,
        default=None,
        help='Comma separated list of vsini values to include in the ccf set')
    parser.add_argument('--every',
                        type=int,
                        default=30,
                        help='Subsample the input grid by this amount')

    args = parser.parse_args(args)

    npoints = int((args.lambda1 - args.lambda0) / args.step)
    ccfconf = CCFConfig(logl0=np.log(args.lambda0),
                        logl1=np.log(args.lambda1),
                        npoints=npoints)

    if args.vsinis is not None:
        vsinis = [float(_) for _ in args.vsinis.split(',')]
    else:
        vsinis = None
    ccf_executor(args.setup,
                 ccfconf,
                 args.prefix,
                 args.oprefix,
                 args.every,
                 vsinis,
                 revision=args.revision)


if __name__ == '__main__':
    main(sys.argv[1:])
