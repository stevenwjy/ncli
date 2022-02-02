use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use log::debug;

mod kindle;
mod notion;

use crate::config::Config;

#[derive(Parser, Debug)]
#[clap(name = "ncli", version = "0.1.0")]
/// Note-taking CLI.
///
/// CLI to make your life easier in managing your notes. Everything just works.
/// You can focus on productively taking your notes and leave the menial tasks
/// for this app to handle.
pub struct Cli {
    #[clap(subcommand)]
    command: Command,

    /// Path to the config file.
    #[clap(long, parse(from_os_str), default_value = "~/.ncli/config.toml")]
    config: PathBuf,
}

impl Cli {
    pub fn run(&self) -> Result<()> {
        debug!("Running command: {:?}", self);

        let conf = Config::load(self.config.clone())?;

        self.command.run(conf)
    }
}

#[derive(Subcommand, Debug)]
enum Command {
    Notion(notion::Subcli),
    Kindle(kindle::Subcli),
}

impl Command {
    fn run(&self, conf: Config) -> Result<()> {
        match self {
            Command::Notion(subcli) => subcli.run(), // we don't really need config for now
            Command::Kindle(subcli) => {
                subcli.run(conf.kindle.expect("unable to find kindle config"))
            }
        }
    }
}
