"""
Support for slackpkg
"""

import collections
import copy
import glob
import logging
import os
import re

import salt.utils.decorators.path
import salt.utils.itertools
import salt.utils.path
import salt.utils.versions
from salt.exceptions import CommandExecutionError, MinionError

log = logging.getLogger(__name__)

# Define the module's virtual name
__virtualname__ = "pkg"

pkgdb = "var/log/packages"


def __virtual__():
    """
    Confine this module to Slackware based systems
    """
    if not salt.utils.path.which("slackpkg"):
        return (
            False,
            "The slackpkg execution module load failed: slackpkg command is missing.",
        )
    try:
        os_family = __grains__["os_family"]
    except Exception:  # pylint: disable=broad-except
        return (
            False,
            "The slackpkg execution module load failed: didn't detect os_family grain.",
        )

    if os_family == "Slackware":
        return __virtualname__
    return (
        False,
        "The slackpkg execution module load failed: {} family not supported".format(
            os_family
        ),
    )


def _pkginfo(package):
    name, version, arch, build = package.rsplit("-", 3)
    pkginfo_tuple = collections.namedtuple(
        "PkgInfo",
        ("name", "version", "arch", "build"),
    )
    return pkginfo_tuple(name, version, arch, build)


def _pkglist(prefix):
    ret = []
    lines = glob.glob("{}/*".format(prefix))
    for line in lines:
        package = line.rsplit("/", 1)[1]
        ret.append(_pkginfo(package))
    return ret


def _list_pkgs_from_context(versions_as_list):
    if versions_as_list:
        return __context__["pkg.list_pkgs"]
    else:
        ret = copy.deepcopy(__context__["pkg.list_pkgs"])
        __salt__["pkg_resource.stringfy"](ret)
        return ret


def list_pkgs(versions_as_list=False, **kwargs):
    """
    List the packages currently installed in a dict::

        {'<package_name>': '<version>'}

    versions_as_list:
        If set to true, the versions are provided as a list:

        {'<package_name>': ['<version>', '<version>']}

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.list_pkgs
    """
    # not yet implemented or not applicable
    if any(
        [salt.utils.data.is_true(kwargs.get(x)) for x in ("removed", "purge_desired")]
    ):
        return {}

    if not kwargs.get("root"):
        root = "/"
    prefix = root + pkgdb

    if "pkg.list_pkgs" in __context__ and kwargs.get("use_context", True):
        return _list_pkgs_from_context(versions_as_list)

    ret = {}
    for package in _pkglist(prefix):
        __salt__["pkg_resource.add_pkg"](
            ret, package[0], "{}-{}".format(package[1], package[3])
        )

    __salt__["pkg_resource.sort_pkglist"](ret)

    if not versions_as_list:
        __salt__["pkg_resource.stringify"](ret)

    return ret


def refresh_db(**kwargs):
    """
    Updates the remote repos database

    Returns:

    - ``True``: Updates are available
    - ``False``: An error occurred
    - ``None``: No updates are available

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.refresh_db
    """
    ret = None
    errors = []
    cmd = "/usr/sbin/slackpkg check-updates"
    out = __salt__["cmd.run_all"](cmd, ignore_retcode=True, output_loglevel="trace")

    if 100 == out["retcode"]:
        ret = True
    elif 1 == out["retcode"]:
        ret = False
        errors.append(out["stderr"])

    if ret:
        cmd = "/usr/sbin/slackpkg -batch=on -default_answer=y update"
        out = __salt__["cmd.run_all"](cmd, ignore_retcode=True, output_loglevel="trace")

        if 1 == out["retcode"]:
            errors.append(out["stderr"])

    if errors:
        raise CommandExecutionError(
            "Problems encountered installing package(s)",
            info={"changes": ret, "errors": errors},
        )

    return ret


def latest_version(*packages, **kwargs):
    """
    Return the latest version of the named package available for upgrade or
    installation. If more than one package name is specified, a dict of
    name/version pairs is returned.

    If the latest version of a given package is already installed, an empty
    string will be returned for that package.

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.latest_version <package name>
        salt '*' pkg.latest_version <package1> <package2> <package3> ...
    """
    ret = {}
    if not packages:
        return ""

    if salt.utils.data.is_true(kwargs.pop("refresh", True)):
        refresh_db()

    localpkgs = list_pkgs()

    with salt.utils.files.fopen("/var/lib/slackpkg/pkglist", "r") as pkglist:
        for line in pkglist:
            if any(" " + package + " " in line for package in packages):
                _, pkgname, version, _, build, _, _, _ = line.split(" ")
                pkgversion = "{}-{}".format(version, build)
                if localpkgs[pkgname] == pkgversion:
                    pkgversion = ""
                ret[pkgname] = pkgversion

    # Return a string if only one package name passed
    if len(packages) == 1:
        return ret[packages[0]]
    return ret


def upgrade_available(name, **kwargs):
    """
    Check whether or not an upgrade is available for a given package

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.upgrade_available <package name>
    """
    return latest_version(name) != ""


def version(*packages, **kwargs):
    """
    Common interface for obtaining the version of installed package.

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.version vim
        salt '*' pkg.version foo bar baz
    """
    return __salt__["pkg_resource.version"](*packages, **kwargs)


def install(
    name=None,
    refresh=False,
    skip_verify=False,
    pkgs=None,
    sources=None,
    downloadonly=False,
    reinstall=False,
    normalize=True,
    update_holds=False,
    saltenv="base",
    ignore_epoch=False,
    **kwargs
):
    """
    Install specified packages

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.install /tmp/packages/foo-1.2.3-x86_64-1.txz
        salt '*' pkg.install pkgs='["foo", "bar"]'
    """
    reinstall = salt.utils.data.is_true(reinstall)

    if name and (name.startswith("/") or "://" in name):
        pkgname = os.path.basename(name).rsplit("-", 3)[0]
        sources = [{pkgname: name}]

    try:
        pkg_params, pkg_type = __salt__["pkg_resource.parse_targets"](
            name, pkgs, sources, saltenv=saltenv, normalize=normalize, **kwargs
        )
    except MinionError as exc:
        raise CommandExecutionError(exc)

    if pkg_params is None or len(pkg_params) == 0:
        return {}

    if salt.utils.data.is_true(refresh):
        refresh_db()

    old = list_pkgs()

    errors = []

    log.debug("Installing these packages: %s", pkg_params)
    if pkg_type == "file":
        for package in pkg_params:
            cmd = "/sbin/installpkg "
            pkgname = os.path.basename(package).rsplit("-", 3)[0]
            if not reinstall:
                if pkgname in old:
                    log.debug("Skipping %s: Already installed", pkgname)
                    continue
            log.debug("Installing %s with %s", pkgname, package)
            cmd += package
            out = __salt__["cmd.run_all"](cmd, output_loglevel="trace")

            if 0 != out["retcode"]:
                errors.append(out["stderr"])

    elif pkg_type == "repository":
        to_install = ""
        to_reinstall = ""
        for package in pkg_params:
            if package in old:
                if reinstall:
                    to_reinstall += package + " "
            else:
                to_install += package + " "

        if to_install:
            cmd = "/usr/sbin/slackpkg -batch=on -default_answer=y "
            cmd += "install "
            cmd += to_install
            out = __salt__["cmd.run_all"](
                cmd,
                ignore_retcode=True,
                output_loglevel="trace",
                env='{"TERSE": "0"}',
            )

            if 1 == out["retcode"]:
                errors.append(out["stderr"])

        if to_reinstall:
            cmd = "/usr/sbin/slackpkg -batch=on -default_answer=y "
            cmd += "reinstall "
            cmd += to_reinstall
            out = __salt__["cmd.run_all"](
                cmd,
                ignore_retcode=True,
                output_loglevel="trace",
                env='{"TERSE": "0"}',
            )

            if 1 == out["retcode"]:
                errors.append(out["stderr"])
    else:
        errors.append("Package type {} not supported by slackpkg".format(pkg_type))

    new = list_pkgs()

    ret = salt.utils.data.compare_dicts(old, new)

    if errors:
        raise CommandExecutionError(
            "Problems encountered installing package(s)",
            info={"changes": ret, "errors": errors},
        )

    return ret


def upgrade(
    name=None,
    refresh=False,
    skip_verify=False,
    pkgs=None,
    sources=None,
    normalize=True,
    update_holds=False,
    saltenv="base",
    ignore_epoch=False,
    **kwargs
):
    """
    Upgrade specified packages

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.upgrade foo
        salt '*' pkg.upgrade pkgs='["foo", "bar"]'
    """
    if name or pkgs or sources:
        if name and (name.startswith("/") or "://" in name):
            pkgname = os.path.basename(name).rsplit("-", 3)[0]
            sources = [{pkgname: name}]

        try:
            pkg_params, pkg_type = __salt__["pkg_resource.parse_targets"](
                name, pkgs, sources, saltenv=saltenv, normalize=normalize, **kwargs
            )
        except MinionError as exc:
            raise CommandExecutionError(exc)

        if pkg_params is None or len(pkg_params) == 0:
            return {}
    else:
        pkg_type = "repository"
        pkg_params = "all system"

    if salt.utils.data.is_true(refresh):
        refresh_db()

    old = list_pkgs()

    errors = []

    log.debug("Upgrading these packages: %s", pkg_params)
    cmd = "/usr/sbin/slackpkg -batch=on -default_answer=y "
    if pkg_type == "file":
        for package in pkg_params:
            cmd = "/sbin/upgradepkg "
            pkgname = os.path.basename(package).rsplit("-", 3)[0]
            if pkgname not in old:
                log.debug("Skipping %s: Not installed", pkgname)
                continue
            log.debug("Upgrading %s with %s", pkgname, package)
            cmd += package
            out = __salt__["cmd.run_all"](cmd, output_loglevel="trace")

            if 0 != out["retcode"]:
                errors.append(out["stderr"])

    elif pkg_type == "repository":
        if pkg_params == "all system":
            cmd += "upgrade-all"
            out = __salt__["cmd.run_all"](
                cmd,
                ignore_retcode=True,
                output_loglevel="trace",
                env='{"TERSE": "0"}',
            )

            if 1 == out["retcode"]:
                errors.append(out["stderr"])
        else:
            to_upgrade = ""
            for package in pkg_params:
                if package in old:
                    to_upgrade += package + " "

            if to_upgrade:
                cmd += "upgrade "
                cmd += to_upgrade
                out = __salt__["cmd.run_all"](
                    cmd,
                    ignore_retcode=True,
                    output_loglevel="trace",
                    env='{"TERSE": "0"}',
                )

        if 1 == out["retcode"]:
            errors.append(out["stderr"])
    else:
        errors.append("Package type {} not supported by slackpkg".format(pkg_type))

    new = list_pkgs()

    ret = salt.utils.data.compare_dicts(old, new)

    if errors:
        raise CommandExecutionError(
            "Problems encountered upgrading package(s)",
            info={"changes": ret, "errors": errors},
        )

    return ret


def remove(name=None, pkgs=None, test=False, **kwargs):
    """
    Remove specified packages

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.remove foo
    """
    packages = salt.utils.args.split_input(pkgs) if pkgs else [name]
    if not packages:
        return {}

    log.debug("Removing these packages: %s", packages)

    old = list_pkgs()

    errors = []
    for package in packages:
        cmd = "/sbin/removepkg "
        if package not in old:
            continue
        log.debug("Removing %s", package)
        cmd += package
        out = __salt__["cmd.run_all"](cmd, output_loglevel="trace")

        if 0 != out["retcode"]:
            errors.append(out["stderr"])

    new = list_pkgs()

    ret = salt.utils.data.compare_dicts(old, new)

    if errors:
        raise CommandExecutionError(
            "Problems encountered removing package(s)",
            info={"changes": ret, "errors": errors},
        )

    return ret


def list_upgrades(refresh=True, **kwargs):  # pylint: disable=W0613
    """
    Lists all packages available for update.

    refresh : True
        Runs a full package database refresh before listing. Set to ``False`` to
        disable running the refresh.

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.list_upgrades
        salt '*' pkg.list_upgrades refresh=False
    """
    if salt.utils.data.is_true(refresh):
        refresh_db()

    cmd = "/usr/sbin/slackpkg -batch=on -default_answer=n upgrade-all "
    pkgregex = re.compile(r'(.*)\.t.z$')
    upgrades = {}

    lines = __salt__["cmd.run_stdout"](
        cmd,
        ignore_retcode=True,
        output_loglevel="trace",
        env='{"TERSE": "0"}',
    ).splitlines()
    for line in lines:
        pkgname = pkgregex.match(line)
        if pkgname:
            package = _pkginfo(pkgname[1])
            upgrades[package[0]] = "{}-{}".format(package[1], package[3])
    return upgrades
