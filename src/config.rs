use std::path::PathBuf;

use anyhow::{anyhow, Result};
use config_rs::{Config as ConfigRs, File};
use log::debug;
use serde::{Deserialize, Serialize};

use crate::kindle::Config as KindleConfig;
use crate::notion::Config as NotionConfig;

#[derive(Debug, Serialize, Deserialize)]
pub struct Config {
    pub notion: Option<NotionConfig>,
    pub kindle: Option<KindleConfig>,
}

impl Config {
    pub fn load(path: PathBuf) -> Result<Config> {
        // Handle home dir
        let config_path;
        if path.starts_with("~") {
            let mut new_path = PathBuf::from(std::env::var("HOME").unwrap());
            new_path.push(path.strip_prefix("~").unwrap());
            config_path = new_path;
        } else {
            config_path = path
        }

        debug!("checking config path: {:?}", config_path);

        if !config_path.exists() {
            return Err(anyhow!("config path does not exist"));
        }

        let s = ConfigRs::builder()
            .add_source(File::from(config_path.as_path()))
            .build()?;
        let conf: Config = s.try_deserialize()?;

        Ok(conf)
    }
}
