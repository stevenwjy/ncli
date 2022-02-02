use std::path::PathBuf;

use anyhow::Result;
use clap::{Args, Subcommand};

use crate::kindle;
use crate::kindle::Config;

#[derive(Args, Debug)]
pub struct Subcli {
    #[clap(subcommand)]
    command: Command,
}

impl Subcli {
    pub fn run(&self, conf: Config) -> Result<()> {
        self.command.run(conf)
    }
}

#[derive(Subcommand, Debug)]
enum Command {
    Export(ExportCommand),
}

impl Command {
    pub fn run(&self, conf: Config) -> Result<()> {
        match self {
            Command::Export(subcmd) => subcmd.run(conf),
        }
    }
}

#[derive(Args, Debug)]
struct ExportCommand {
    /// Path to the target location for the export.
    #[clap(long, parse(from_os_str))]
    target: PathBuf,

    /// If headless argument is provided, the export operation will be performed headless.
    #[clap(long)]
    headless: bool,
}

impl ExportCommand {
    pub fn run(&self, conf: Config) -> Result<()> {
        let opts = kindle::ExportOpts {
            target: self.target.clone(),
            headless: self.headless,
            email: conf.email,
            password: conf.password,
        };

        kindle::export(opts)
    }
}
