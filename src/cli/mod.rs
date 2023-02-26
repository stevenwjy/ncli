use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use log::debug;

use crate::config::Config;

mod audible;
mod kindle;
mod notion;

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
    Audible(audible::Subcli),
    Kindle(kindle::Subcli),
    Notion(notion::Subcli),
}

impl Command {
    fn run(&self, conf: Config) -> Result<()> {
        match self {
            Command::Audible(subcli) => subcli.run(),
            Command::Kindle(subcli) => {
                subcli.run(conf.kindle.expect("unable to find kindle config"))
            }
            Command::Notion(subcli) => subcli.run(),
        }
    }
}
