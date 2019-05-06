r"""
Power spectrum

This module implements the ell-dependent component of common foreground
contaminants.

This module draws inspiration from FGBuster (Davide Poletti and Josquin Errard)
and BeFoRe (David Alonso and Ben Thorne).
"""

import os
import pkg_resources
from abc import ABC, abstractmethod
import numpy as np


def _get_power_file(model):
    """ File path for the named model
    """
    data_path = pkg_resources.resource_filename('fgspectra', 'data/')
    filename = os.path.join(data_path, 'cl_%s.dat'%model)
    if os.path.exists(filename):
        return filename
    raise ValueError('No template for model '+model)


class PowerSpectrum(ABC):
    """Base class for frequency dependent components."""

    @abstractmethod
    def __call__(self, ell, *args):
        """Make component objects callable."""
        pass


class PowerSpectrumFromFile(PowerSpectrum):
    """Power spectrum loaded from file(s)

    Parameters
    ----------
    filenames: array_like of strings
        File(s) to load. It can be a string or any (nested) sequence of strings

    Examples
    --------

    >>> ell = range(5)

    Power spectrum of a single file

    >>> my_file = 'cl.dat'
    >>> ps = PowerSpectrumFromFile(my_file)
    >>> ps(ell).shape
    (5)
    >>> ps = PowerSpectrumFromFile([my_file])  # List
    >>> ps(ell).shape
    (1, 5)

    Two correlated components

    >>> my_files = [['cl_comp1.dat', 'cl_comp1xcomp2.dat'],
    ...             ['cl_comp1xcomp2.dat', 'cl_comp2.dat']]
    >>> ps = PowerSpectrumFromFile(my_files)
    >>> ps(ell).shape
    (2, 2, 5)

    """

    def __init__(self, filenames):
        """

        The file format should be two columns, ell and the spectrum.
        """
        filenames = np.array(filenames)
        self._cl = np.empty(filenames.shape+(0,))

        for i, filename in np.ndenumerate(filenames):
            ell, spec = np.genfromtxt(filename, unpack=True)
            ell = ell.astype(int)
            # Make sure that the new spectrum fits self._cl
            n_missing_ells = ell.max() + 1 - self._cl.shape[-1]
            if n_missing_ells > 0:
                pad_width = [(0,0)] * self._cl.ndim
                pad_width[-1] = (0, n_missing_ells)
                self._cl = np.pad(self._cl, pad_width, 
                                  mode='constant', constant_values=0)

            self._cl[i+(ell,)] = spec


    def __call__(self, ell, ell_0=3000):
        """Compute the power spectrum with the given ell and parameters."""
        return self._cl[..., ell] / self._cl[..., ell_0]


class tSZ_150_bat(PowerSpectrumFromFile):
    """PowerSpectrum for Thermal Sunyaev-Zel'dovich (Dunkley et al. 2013)."""

    def __init__(self):
        """Intialize object with parameters."""
        super().__init__(_get_power_file('tsz_150_bat'))


class kSZ_bat(PowerSpectrumFromFile):
    """PowerSpectrum for Kinematic Sunyaev-Zel'dovich (Dunkley et al. 2013)."""

    def __init__(self):
        """Intialize object with parameters."""
        super().__init__(_get_power_file('ksz_bat'))


class PowerLaw(PowerSpectrum):
    r""" Power law

    .. math:: C_\ell = (\ell / \ell_0)^\alpha
    """
    def __call__(self, ell, alpha, ell_0):
        """

        Parameters
        ----------
        ell: float or array
            Multipole
        alpha: float or array
            Spectral index.
        ell_0: float
            Reference ell

        Returns
        -------
        cl: ndarray
            The last dimension is ell.
            The leading dimensions are the hypothetic dimensions of `alpha`
        """
        alpha = np.array(alpha)[..., np.newaxis]
        return (ell / ell_0)**alpha


class PowerSpectraAndCorrelation(PowerSpectrum):
    r"""Components' spectra and their correlation

    Spectrum of correlated components defined by the spectrum of each component
    and their correlation

    Parameters
    ----------
    *power_spectra : series of `PowerSpectrum`
        The series has lenght :math:`N (N + 1) / 2`, where :math:`N` is the
        number of components. They specify the upper (or lower) triangle of the
        component-component cross spectra, which is symmetric. The series stores
        the main diagonal (i.e. the autospectra) goes first, the second diagonal
        of the correlation matrix follows, then the third, etc.
        The ordering is similar to the one returned by `healpy.anafast`.
    """


    def __init__(self, *power_spectra):
        self._power_spectra = power_spectra
        self.n_comp = np.rint(-1 + np.sqrt(1 + 8 * len(power_spectra))) // 2
        self.n_comp = int(self.n_comp)
        assert (self.n_comp + 1) * self.n_comp // 2 == len(power_spectra)

    def __call__(self, *argss):
        """Compute the SED with the given frequency and parameters.

        *argss
            The length of `argss` has to be equal to the number of SEDs joined.
            ``argss[i]`` is the argument list of the ``i``-th SED.
        """
        spectra = [ps(*args) for ps, args in zip(self._power_spectra, argss)]
        corrs = spectra[self.n_comp:]
        cls = spectra[:self.n_comp]
        sqrt_cls = [np.sqrt(cl) for cl in cls]
        cls_shape = np.broadcast(*cls).shape

        res = np.empty(  # Shape is (..., comp, comp, ell)
            cls_shape[1:-1] + (self.n_comp, self.n_comp) + cls_shape[-1:])

        for i in range(self.n_comp):
            res[..., i, i, :] = cls[i]

        i_corr = 0
        for k_off_diag in range(1, self.n_comp):
            for el_off_diag in range(self.n_comp - k_off_diag):
                i = el_off_diag
                j = el_off_diag + k_off_diag
                res[..., i, j, :] = sqrt_cls[i] * sqrt_cls[j] * corrs[i_corr]
                res[..., j, i, :] = res[..., i, j, :]
                i_corr += 1

        '''
        i_corr = 0
        for i in range(self.n_comp):
            res[..., i, i, :] = cls[i]
            for j in range(i + 1, self.n_comp):
                res[..., i, j, :] = sqrt_cls[i] * sqrt_cls[j] * corrs[i_corr]
                res[..., j, i, :] = res[..., i, j, :]
                i_corr += 1
        '''

        assert i_corr == len(corrs)
        return res


class SZxCIB(PowerSpectraAndCorrelation):
    """PowerSpectrum for SZxCIB (Dunkley et al. 2013)."""

    def __init__(self):
        """Intialize object with parameters."""
        power_spectra = [
            PowerSpectrumFromFile(_get_power_file('tsz_150_bat')),
            PowerLaw(),
            PowerSpectrumFromFile(_get_power_file('sz_x_cib'))
        ]
        super().__init__(*power_spectra)


# Power law in ell

# Extragalactic FGs: from tile-c?? or Erminia / Jo

# CMB template cls?
