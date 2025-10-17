# slackware-salt

This repository contains a recipe to build a package for Slackware using the official [Salt Project](https://saltproject.io/)'s Salt Onedir release with a few extras:

- `pkg` execution module to handle Slackware packages. For backend it uses slackpkg and pkgtools.
- RC-scripts to manage `salt-master`, `salt-minion` and `salt-syndic` daemons.

## How to use this recipe

To use this repository, clone it:
```
git clone https://github.com/piterpunk/slackware-salt
```
Enter in the created directory:
```
cd slackware-salt
```
Run the `salt-onedir.Slackbuild`:
```
DOWNLOAD=true ./salt-onedir.Slackbuild
```
The package name will be shown at the end of execution in a message like this one:
```
Slackware package /tmp/salt-onedir-3007.8-x86_64-2pk.tgz created.
```
Now you need to install or upgrade to this package using `installpkg` or `upgradepkg` commands:
```
installpkg /tmp/salt-onedir-3007.8-x86_64-2pk.tgz
```
## Post-install

After install the package, remember to add something like these lines to your `/etc/rc.d/rc.local`:
```
if [ -x /etc/rc.d/rc.salt-master ]; then
        /etc/rc.d/rc.salt-master start
fi

if [ -x /etc/rc.d/rc.salt-minion ]; then
        /etc/rc.d/rc.salt-minion start
fi

if [ -x /etc/rc.d/rc.salt-syndic ]; then
        /etc/rc.d/rc.salt-syndic start
fi
```
And enables the daemon that you want to run in your machine (usually the `salt-minion`):
```
chmod +x /etc/rc.d/rc.salt-minion
```

