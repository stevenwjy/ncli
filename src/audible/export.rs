use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use anyhow::{anyhow, Result};
use log::{info, warn};

use crate::audible::api::{Chapter, GetAnnotationsResponse, GetChaptersResponse};

use super::api::Record;

const RECORD_TYPE_CLIP: &str = "audible.clip";
const FILE_EXTENSION_JSON: &str = "json";
const FILE_EXTENSION_PDF: &str = "pdf";
const FILE_STEM_SUFFIX_CHAPTERS: &str = "-chapters";
const FILE_STEM_SUFFIX_ANNOTATIONS: &str = "-annotations";

pub struct ExportOpts {
    pub source: PathBuf,
    pub target: PathBuf,
    pub force: bool,
    pub clean: bool,
}

pub fn export(opts: ExportOpts) -> Result<()> {
    // Check existence of the target directory
    if opts.target.exists() {
        if !opts.force {
            return Err(anyhow!("target path '{:?}' already exists", opts.target));
        }

        warn!(
            "Target path '{:?}' already exists. Removing it since force option is used.",
            opts.target
        );
        if opts.target.is_dir() {
            fs::remove_dir_all(&opts.target)?;
        } else {
            fs::remove_file(&opts.target)?;
        }
    }

    // Create the target directory
    info!("Creating target directory: {:?}", opts.target);
    fs::create_dir_all(&opts.target)?;

    let mut exporters = get_book_exporters(&opts.source, &opts.target)?;

    info!("Building target directory");
    for exporter in exporters.iter_mut() {
        info!("Building book: {}", exporter.title);
        exporter.write_all()?;
    }

    // Optionally remove the source dir
    if opts.clean {
        info!("Removing the source directory");
        fs::remove_file(&opts.source)?;
    }

    info!("Export operation has been executed successfully");

    Ok(())
}

fn get_book_exporters(source_dir: &PathBuf, target_dir: &PathBuf) -> Result<Vec<BookExporter>> {
    if !source_dir.exists() {
        return Err(anyhow!("source path does not exist"));
    } else if !source_dir.is_dir() {
        return Err(anyhow!("source path must be a directory"));
    }

    let mut book_entries: HashMap<String, BookEntry> = HashMap::new();

    for item in fs::read_dir(source_dir)? {
        let path = item?.path();
        let file_name = path
            .file_name()
            .ok_or(anyhow!("unknown file name"))?
            .to_str()
            .unwrap();

        if !path.is_file() {
            warn!("found non-file path: '{}'. skipping.", file_name);
            continue;
        } else if path.extension().is_none() {
            warn!("found file without extension: '{}'. skipping.", file_name);
            continue;
        } else if path.file_stem().is_none() {
            warn!(
                "found file without stem (name without extension): '{}'. skipping.",
                file_name
            );
            continue;
        }

        // Already checked the existence above
        let extension = path.extension().unwrap().to_str().unwrap();
        let file_stem = path.file_stem().unwrap().to_str().unwrap();

        match extension {
            FILE_EXTENSION_JSON => {
                if let Some(title) = file_stem.strip_suffix(FILE_STEM_SUFFIX_CHAPTERS) {
                    book_entries
                        .entry(title.to_string())
                        .or_insert_with(|| empty_book_entry())
                        .chapter = Some(path.clone());
                } else if let Some(title) = file_stem.strip_suffix(FILE_STEM_SUFFIX_ANNOTATIONS) {
                    book_entries
                        .entry(title.to_string())
                        .or_insert_with(|| empty_book_entry())
                        .annotation = Some(path.clone());
                } else {
                    warn!(
                        "found json file with unexpected name format: '{}'. skipping.",
                        file_name
                    );
                    continue;
                }
            }
            FILE_EXTENSION_PDF => {
                book_entries
                    .entry(file_stem.to_string())
                    .or_insert_with(|| empty_book_entry())
                    .pdf = Some(path.clone());
            }
            _ => {
                warn!(
                    "found file with unexpected extension: '{}'. skipping.",
                    file_name
                );
                continue;
            }
        }
    }

    let mut exporters = vec![];
    for (title, entry) in book_entries.into_iter() {
        if entry.chapter.is_none() {
            warn!(
                "found a book without any chapter file: '{}'. skipping",
                title
            );
            continue;
        }

        let chapter = {
            info!(
                "reading file: {}",
                entry.chapter.as_ref().unwrap().to_str().unwrap()
            );
            let text = fs::read_to_string(entry.chapter.unwrap())?;
            serde_json::from_str::<GetChaptersResponse>(&text)
        }?;

        let mut annotation = None;
        if let Some(annotation_path) = &entry.annotation {
            annotation = Some({
                info!("reading file: {}", annotation_path.to_str().unwrap());
                let text = fs::read_to_string(annotation_path)?;
                serde_json::from_str::<GetAnnotationsResponse>(&text)
            }?);
        }

        let file = fs::File::create(target_dir.join(format!("{}.md", title)))?;
        let md_file_writer = BufWriter::new(file);

        exporters.push(BookExporter {
            target_dir: target_dir.clone(),
            w: md_file_writer,
            title: title.clone(),
            chapter: chapter,
            annotation: annotation,
            pdf_path: entry.pdf,
        })
    }

    Ok(exporters)
}

fn empty_book_entry() -> BookEntry {
    BookEntry {
        chapter: None,
        annotation: None,
        pdf: None,
    }
}

struct BookEntry {
    chapter: Option<PathBuf>,
    annotation: Option<PathBuf>,
    pdf: Option<PathBuf>,
}

struct BookExporter {
    target_dir: PathBuf,

    // Writer to the markdown file where we will write the book data.
    w: BufWriter<File>,

    // Parsed data

    // Note that the title of the book here is a "safe string" with underscore
    // as separator between words.
    title: String,

    chapter: GetChaptersResponse,
    annotation: Option<GetAnnotationsResponse>,
    pdf_path: Option<PathBuf>,
}

impl BookExporter {
    fn write_all(&mut self) -> Result<()> {
        self.copy_pdf_if_exists()?;

        self.write_headers()?;

        writeln!(&mut self.w, "")?;
        writeln!(&mut self.w, "## Table of Contents")?;
        writeln!(&mut self.w, "")?;

        let chapters = self.chapter.content_metadata.chapter_info.chapters.clone();
        self.write_chapters(&chapters, 0)?;

        writeln!(&mut self.w, "")?;
        writeln!(&mut self.w, "## Annotations")?;
        writeln!(&mut self.w, "")?;

        self.write_annotations()?;

        Ok(())
    }

    fn copy_pdf_if_exists(&self) -> Result<()> {
        // No-op if there's no PDF associated with the book.
        if self.pdf_path.is_none() {
            return Ok(());
        }

        let path = self.pdf_path.clone().unwrap();
        info!("copying file: {}", path.to_str().unwrap());
        fs::copy(path, self.target_dir.join(format!("{}.pdf", self.title)))?;

        Ok(())
    }

    fn write_headers(&mut self) -> Result<()> {
        writeln!(&mut self.w, "---")?;

        writeln!(
            &mut self.w,
            "asin: {}",
            self.chapter.content_metadata.content_reference.asin
        )?;
        writeln!(&mut self.w, "title: {}", self.title)?;

        if let Some(last_heard) = &self
            .chapter
            .content_metadata
            .last_position_heard
            .last_updated
        {
            writeln!(&mut self.w, "last_heard: {}", last_heard)?;
        } else {
            writeln!(&mut self.w, "last_heard: -")?;
        }
        writeln!(&mut self.w, "")?;
        writeln!(&mut self.w, "---")?;
        writeln!(&mut self.w, "")?;

        if self.pdf_path.is_some() {
            writeln!(&mut self.w, "PDF: [link](./{}.pdf)", self.title)?;
            writeln!(&mut self.w, "")?;
            writeln!(&mut self.w, "---")?;
            writeln!(&mut self.w, "")?;
        }

        Ok(())
    }

    fn write_chapters(&mut self, chapters: &Vec<Chapter>, depth: usize) -> Result<()> {
        for chapter in chapters {
            writeln!(
                &mut self.w,
                "{}- {}   |   [start: {}, duration: {}]",
                " ".repeat(2 * depth),
                chapter.title,
                chapter.start_offset_ms,
                chapter.length_ms,
            )?;

            if let Some(subchapters) = &chapter.chapters {
                self.write_chapters(&subchapters, depth + 1)?;
            }
        }
        Ok(())
    }

    fn write_annotations(&mut self) -> Result<()> {
        if self.annotation.is_none() {
            writeln!(&mut self.w, "-")?;
            writeln!(&mut self.w, "")?;
            return Ok(());
        }

        let data = self.annotation.as_ref().unwrap();
        let annotations = parse_annotations(&data.payload.records);

        writeln!(&mut self.w, "version (md5): {}", data.md5)?;
        writeln!(&mut self.w, "")?;
        writeln!(&mut self.w, "---")?;
        writeln!(&mut self.w, "")?;

        for annotation in annotations {
            writeln!(&mut self.w, "**Created:** {}", annotation.creation_time)?;
            writeln!(&mut self.w, "")?;
            writeln!(
                &mut self.w,
                "**Last modified:** {}",
                annotation.creation_time
            )?;
            writeln!(&mut self.w, "")?;
            // TODO: Convert clip range into more readable value (e.g., identify based on chapter start and end ts)
            writeln!(
                &mut self.w,
                "**Clip range:** [{}, {}]",
                annotation.start_position, annotation.end_position
            )?;
            writeln!(&mut self.w, "")?;
            if let Some(note) = annotation.note {
                writeln!(&mut self.w, "**Note:** {}", note)?;
                writeln!(&mut self.w, "")?;
            }
            writeln!(&mut self.w, "---")?;
            writeln!(&mut self.w, "")?;
        }

        Ok(())
    }
}

fn parse_annotations(records: &Vec<Record>) -> Vec<Annotation> {
    let mut res = vec![];

    for record in records {
        // We will only process records of type clip here as we only want to retrieve
        // the annotations and clip is a superset of bookmark and note.
        if record.record_type != RECORD_TYPE_CLIP {
            continue;
        }

        let mut note = None;
        let mut note_version = None;
        if let Some(meta) = &record.metadata {
            if meta.note.is_some() {
                note = Some(meta.note.clone().unwrap());
                note_version = Some(meta.c_version.parse().unwrap());
            }
        }

        res.push(Annotation {
            start_position: record.start_position.clone().parse().unwrap(),
            end_position: record.end_position.clone().unwrap().parse().unwrap(),
            creation_time: record.creation_time.clone(),

            annotation_id: record.annotation_id.clone().unwrap(),
            last_modification_time: record.last_modification_time.clone().unwrap(),

            note: note,
            note_version: note_version,
        });
    }

    return res;
}

struct Annotation {
    pub start_position: u32,
    pub end_position: u32,
    pub creation_time: String,

    pub annotation_id: String,
    pub last_modification_time: String,

    // Optional note attached to the clip
    pub note: Option<String>,
    pub note_version: Option<u32>,
}
