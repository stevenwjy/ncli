use std::path::PathBuf;

use clap::{Args, Subcommand};

use crate::exec::Exec;

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
    Extract {
        /// Path to the directory exported from Kindle. Note that since Kindle
        /// by default gives you a ZIP file, you need to unzip it first.
        #[clap(parse(from_os_str))]
        source: PathBuf,

        /// Path to the target location after the conversion.
        #[clap(parse(from_os_str))]
        target: PathBuf,
    },
}

impl Exec for Command {
    fn run(&self) {}
}
