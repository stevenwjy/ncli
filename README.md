# ncli

## How To Use


Install `geckodriver` if you don't already have it. In Ubuntu, it could come preinstalled at `/snap/bin/geckodriver`.

If you don't already have it, check the latest release [here](https://github.com/mozilla/geckodriver/releases).
Afterward, do the following steps ([ref](https://askubuntu.com/questions/870530/how-to-install-geckodriver-in-ubuntu)):

```
wget https://github.com/mozilla/geckodriver/releases/download/v0.32.0/geckodriver-v0.32.0-linux64.tar.gz
tar -xvzf geckodriver*
chmod +x geckodriver

# May want to edit .zshrc or similar file that you use as well
export PATH=$PATH:/path-to-extracted-file/.
```

Run geckodriver
```
# If you are using the regular Firefox
geckodriver

# If you are using the developer edition
geckodriver -b /Applications/Firefox\ Developer\ Edition.app
```

Create config file at `~/.ncli/config.toml`:

```
[kindle]
email = "your.email@domain.com"
password = "your-password-in-plain-text"
```

Run the program

```
# Kindle
RUST_BACKTRACE=1 RUST_LOG=ncli=debug cargo run -- kindle export --target ../notes/kindle --headless

# Notion
RUST_LOG=ncli=debug cargo run -- notion export --source ../data/hex-filename.zip --target ../notes/notion --force
```
