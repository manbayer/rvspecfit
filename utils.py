import os
import subprocess
import yaml
import frozendict


def get_revision():
    """
    Get the git revision of the code

    Returns:
    --------
    revision : string
        The string with the git revision
    """
    try:
        fname = os.path.dirname(os.path.realpath(__file__))
        tmpout = subprocess.Popen(
            'cd ' + fname + ' ; git log -n 1 --pretty=format:%H -- make_nd.py',
            shell=True, bufsize=80, stdout=subprocess.PIPE).stdout
        revision = tmpout.read()
        return revision
    except:
        return ''


def read_config(fname=None):
    """
    Read the configuration file and return the frozendict with it

    Parameters:
    -----------
    fname: string, optional
        The path to the configuration file. If not given config.yaml in the
        current directory is used

    Returns:
    --------
    config: frozendict
        The dictionary with the configuration from a file
    """
    if fname is None:
        fname = 'config.yaml'
    with open(fname) as fp:
        return freezeDict(yaml.safe_load(fp))


def freezeDict(d):
    """
    Take the input object and if it is a dictionary, freeze it (i.e. return frozendict)
    If not, do nothing

    Parameters:
    d: dict
        Input dictionary

    Returns:
    --------
    d: frozendict
        Frozen input dictionary
    """
    if isinstance(d, dict):
        d1 = {}
        for k, v in d.items():
            d1[k] = freezeDict(v)
        return frozendict.frozendict(d1)
    else:
        return d
