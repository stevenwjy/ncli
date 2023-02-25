use clap::Parser;
use log::{error, info};

mod audible;
mod cli;
mod config;
mod kindle;
mod notion;

fn main() {
    env_logger::init();

    let result = cli::Cli::parse();
    match result.run() {
        Ok(_) => info!("Command has been executed successfully!"),
        Err(err) => error!("Error occured: {:?}", err),
    }
}
