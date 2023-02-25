use std::path::PathBuf;

use anyhow::Result;
use clap::{Args, Subcommand};

use crate::audible;

#[derive(Args, Debug)]
pub struct Subcli {
    #[clap(subcommand)]
    command: Command,
}

impl Subcli {
    pub fn run(&self) -> Result<()> {
        self.command.run()
    }
}

#[derive(Subcommand, Debug)]
enum Command {
    Export(ExportCommand),
}

impl Command {
    pub fn run(&self) -> Result<()> {
        match self {
            Command::Export(subcmd) => subcmd.run(),
        }
    }
}

#[derive(Args, Debug)]
struct ExportCommand {
    /// Path to the zip file exported from Notion. Note that since Notion
    /// by default gives you a ZIP file, you need to unzip it first.
    #[clap(long, parse(from_os_str))]
    source: PathBuf,

    /// Path to the target location after the conversion.
    #[clap(long, parse(from_os_str))]
    target: PathBuf,

    /// If force argument is provided, the current target directory will be
    /// removed if it exists.
    #[clap(long)]
    force: bool,

    /// If clean argument is provided, the source directory will be removed
    /// when the export operation finishes.
    #[clap(long)]
    clean: bool,
}

impl ExportCommand {
    pub fn run(&self) -> Result<()> {
        let opts = audible::ExportOpts {
            source: self.source.clone(),
            target: self.target.clone(),
            force: self.force,
            clean: self.clean,
        };

        audible::export(opts)
    }
}
