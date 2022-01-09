use clap::{Parser, Subcommand};

mod kindle;
mod notion;

use crate::exec::Exec;

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
}

impl Exec for Cli {
    fn run(&self) {
        self.command.run();
    }
}

#[derive(Subcommand, Debug)]
enum Command {
    Notion(notion::Subcli),
    Kindle(kindle::Subcli),
}

impl Exec for Command {
    fn run(&self) {
        match self {
            Command::Notion(subcli) => subcli.run(),
            Command::Kindle(subcli) => subcli.run(),
        }
    }
}
