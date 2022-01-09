use std::io::BufWriter;
use std::path::{Path, PathBuf};
use std::{fs, io::Write};

use anyhow::{anyhow, Result};
use lazy_static::lazy_static;
use regex::Regex;

use log::{info, warn};

lazy_static! {
    static ref VERSIONED_NAME_RE: Regex =
        Regex::new(r"^(.*) ([0-9a-f]{32})(?:.(md|csv))?$").unwrap();
}

const VERSION_FILE_NAME: &str = "version.txt";

pub struct ExportOpts {
    pub source: PathBuf,
    pub target: PathBuf,
    pub force: bool,
    pub clean: bool,
}

pub fn export(opts: ExportOpts) -> Result<()> {
    if !opts.source.exists() || !opts.source.is_dir() {
        return Err(anyhow!("source path must be a valid directory"));
    }

    let entry = build_entry(&opts.source)?;

    // remove target if it currently exists
    if opts.target.exists() {
        if !opts.force {
            return Err(anyhow!("target path '{:?}' already exists", opts.target));
        }

        warn!(
            "Target path '{:?}' already exists. Removing it since force option is used",
            opts.target
        );

        if opts.target.is_dir() {
            fs::remove_dir_all(&opts.target)?;
        } else {
            fs::remove_file(&opts.target)?;
        }
    }

    // create the target directory
    info!("Creating target directory: '{:?}'", opts.target);
    fs::create_dir_all(&opts.target)?;

    let target_name = opts
        .target
        .file_name()
        .ok_or(anyhow!("unable to read target dir name"))?;
    let target_name = target_name
        .to_str()
        .ok_or(anyhow!("unable to convert target dir name to string"))?;
    if !target_name.eq(&entry.name) {
        warn!("The target directory name is different from the source");
    }

    info!("Building target directory");

    build_target(&opts.target, &entry)?;

    if opts.clean {
        info!("Removing the source directory");
        fs::remove_dir_all(opts.source)?;
    }

    info!("Export operation has been executed successfully");

    Ok(())
}

#[derive(Debug)]
struct Entry {
    name: String,
    version: String,
    path: PathBuf,
    kind: EntryKind,
}

#[derive(Debug)]
enum EntryKind {
    File { extension: String },
    Dir { children: Vec<Entry> },
}

fn build_entry(path: &PathBuf) -> Result<Entry> {
    let file_name = path.file_name().ok_or(anyhow!("name not found"))?;
    let file_name = file_name
        .to_str()
        .ok_or(anyhow!("unable to convert file name to string"))?;
    let caps = VERSIONED_NAME_RE
        .captures(file_name)
        .ok_or(anyhow!("invalid versioned file name"))?;

    let name = String::from(caps.get(1).unwrap().as_str());
    let version = String::from(caps.get(2).unwrap().as_str());

    if path.is_dir() {
        let mut children = vec![];
        for child in fs::read_dir(path)? {
            children.push(build_entry(&child?.path())?);
        }

        return Ok(Entry {
            name,
            version,
            path: path.clone(),
            kind: EntryKind::Dir { children },
        });
    } else {
        let extension = String::from(caps.get(3).unwrap().as_str());

        return Ok(Entry {
            name,
            version,
            path: path.clone(),
            kind: EntryKind::File { extension },
        });
    }
}

fn build_target(path: &Path, entry: &Entry) -> Result<()> {
    if let EntryKind::Dir { children } = &entry.kind {
        let version_file = fs::File::create(path.join(VERSION_FILE_NAME))?;
        let mut w = BufWriter::new(version_file);

        writeln!(&mut w, "version: {}", entry.version)?;

        let mut has_file = false;
        for child in children.iter() {
            if let EntryKind::File { extension } = &child.kind {
                let file_name = format!("{}.{}", child.name, extension);
                fs::copy(&child.path, path.join(&file_name))?;

                if !has_file {
                    // Only write this if there is at least one file
                    writeln!(&mut w)?;
                    writeln!(&mut w, "files:")?;
                    has_file = true;
                }

                writeln!(&mut w, "- '{}': '{}'", file_name, child.version)?;
            } else {
                let child_path = path.join(&child.name);
                fs::create_dir(&child_path)?;
                build_target(&child_path, child)?;
            }
        }
    } else {
        panic!("build_target must be called with a directory entry")
    }

    Ok(())
}
