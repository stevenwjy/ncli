use clap::Parser;

mod cli;
mod exec;
mod notion;

use exec::Exec;

fn main() {
    env_logger::init();

    let result = cli::Cli::parse();
    result.run();
}
