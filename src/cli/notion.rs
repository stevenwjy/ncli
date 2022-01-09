use std::path::PathBuf;

use clap::{Args, Subcommand};
use log::{debug, error, info};

use crate::exec::Exec;
use crate::notion;

#[derive(Args, Debug)]
pub struct Subcli {
    #[clap(subcommand)]
    command: Command,
}

impl Exec for Subcli {
    fn run(&self) {
        self.command.run();
    }
}

#[derive(Subcommand, Debug)]
enum Command {
    Extract(ExtractCommand),
}

impl Exec for Command {
    fn run(&self) {
        match self {
            Command::Extract(subcmd) => subcmd.run(),
        }
    }
}

#[derive(Args, Debug)]
struct ExtractCommand {
    /// Path to the directory exported from Notion. Note that since Notion
    /// by default gives you a ZIP file, you need to unzip it first.
    #[clap(short, long, parse(from_os_str))]
    source: PathBuf,

    /// Path to the target location after the conversion.
    #[clap(short, long, parse(from_os_str))]
    target: PathBuf,

    /// If force argument is provided, the current target directory will be
    /// removed if it exists.
    #[clap(short, long)]
    force: bool,

    /// If clean argument is provided, the source directory will be removed
    /// when the export operation finishes.
    #[clap(short, long)]
    clean: bool,
}

impl Exec for ExtractCommand {
    fn run(&self) {
        debug!("Running notion extract command: {:?}", self);

        let opts = notion::ExportOpts {
            source: self.source.clone(),
            target: self.target.clone(),
            force: self.force,
            clean: self.clean,
        };

        match notion::export(opts) {
            Ok(_) => info!("Command has been executed successfully!"),
            Err(err) => error!("Error occured: {:?}", err),
        }
    }
}
