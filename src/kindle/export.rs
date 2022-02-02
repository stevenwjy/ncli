use std::fs;
use std::io::{self, BufWriter, Write};
use std::path::PathBuf;

use anyhow::{anyhow, Result};
use chrono::prelude::*;
use log::warn;
use serde::{Deserialize, Serialize};

use crate::kindle::book::Book;
use crate::kindle::client::{Client, ClientOpts};

use super::annotation::AnnotationList;

const INDEX_FILE_NAME: &str = "index.toml";

pub struct ExportOpts {
    pub target: PathBuf,
    pub headless: bool,

    // Credentials to access Kindle website
    pub email: String,
    pub password: String,
}

pub fn export(opts: ExportOpts) -> Result<()> {
    // Do some preparations for the configurations

    // Guarantee that the export target is valid and is a directory
    if !opts.target.exists() {
        // Create the directory
        fs::create_dir_all(&opts.target)?;
    } else if opts.target.is_file() {
        return Err(anyhow!("export target must be a directory"));
    }

    // NOTE: We try to convert the async fn into a synchronous one here. Also, note that we only
    //       use the current thread to perform the task since we don't really need multiple threads
    //       given the operational costs of this extraction process at the point of writing.
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;

    return runtime.block_on(export_async(opts));
}

async fn export_async(opts: ExportOpts) -> Result<()> {
    let client_opts = ClientOpts {
        headless: opts.headless,
        email: opts.email,
        password: opts.password,
    };

    let mut client = Client::new(client_opts).await;
    let book_library = client.get_books().await?;

    // Load the export index to be cross-checked against the newly fetched library
    let mut index_file_path = opts.target.clone();
    index_file_path.push(INDEX_FILE_NAME);
    let mut export_index = ExportIndex::load_or_default(&index_file_path)?;

    for book in &book_library.books {
        if export_index.check_book(book) {
            let annotation_list = client.get_annotations(book).await?;

            // Note that we will generate the book name using its title and use the ".md" extension since it is
            // a Markdown file.
            let mut book_path = opts.target.clone();
            book_path.push(format!("{}.md", book.title));

            export_data_to_markdown(book, &annotation_list, &book_path)?;
        }
    }

    // Log warning(s) for book(s) that are left unchecked.
    export_index.warn_unchecked_books();

    // Save back the index
    export_index.save(&index_file_path)?;

    // Close after completing the export
    client.close().await?;

    Ok(())
}

fn export_data_to_markdown(
    book: &Book,
    annotation_list: &AnnotationList,
    path: &PathBuf,
) -> Result<()> {
    let file = fs::File::create(path)?;
    let mut w = BufWriter::new(file);

    // Write the file headers using the book info
    //
    // WARN: This does not necessarily match the index since a user could potentially decide to update the index
    //       but not fetch the latest data to be exported.
    writeln!(&mut w, "---")?;
    writeln!(&mut w, "asin: {}", book.asin)?;
    writeln!(&mut w, "title: {}", book.title)?;
    if let Some(subtitle) = &book.subtitle {
        writeln!(&mut w, "subtitle: {}", subtitle)?;
    }
    writeln!(&mut w, "author: {}", book.author)?;
    writeln!(&mut w, "image_url: {}", book.image_url)?;
    writeln!(&mut w, "last_opened_date: {}", book.last_opened_date)?;
    writeln!(&mut w, "")?; // We need this empty line before the closing "---" to avoid unwanted styling
    writeln!(&mut w, "---")?;

    for annotation in &annotation_list.annotations {
        writeln!(&mut w, "")?;
        writeln!(&mut w, "---")?;
        if annotation.highlight.is_some() {
            writeln!(
                &mut w,
                "**{} highlight:**",
                annotation.highlight_color.as_ref().unwrap()
            )?; // color must exist
            writeln!(&mut w, "> {}", annotation.highlight.as_ref().unwrap())?; // WARN: shouldn't have double newlines
            writeln!(&mut w, "")?;
        }

        if annotation.note.is_some() {
            writeln!(&mut w, "**Note:**")?;
            writeln!(&mut w, "{}", annotation.note.as_ref().unwrap())?; // WARN: shouldn't have double newlines
            writeln!(&mut w, "")?;
        }

        if annotation.page.is_some() {
            writeln!(&mut w, "**Page:**")?;
            writeln!(&mut w, "{}", annotation.page.as_ref().unwrap())?;
            writeln!(&mut w, "")?;
        }

        // Since the location always exists, we could always write the link.
        //
        // NOTE: The link only works for Kindle App, since Kindle Web does not seem to support lookup by location?
        writeln!(&mut w, "**Link:**")?;
        writeln!(
            &mut w,
            "[Kindle App](kindle://book?action=open&asin={}&location={})",
            book.asin, annotation.location
        )?;
        writeln!(&mut w, "")?;

        writeln!(&mut w, "---")?;
    }

    Ok(())
}

#[derive(Serialize, Deserialize)]
struct ExportIndex {
    // List of potentially exported books that are recorded in the index.
    //
    // Note that it is possible for a book to exist in the index but has not actually been exported. This is
    // to address the situation if someone has not finished reading a book (and hence does not want to export
    // the data first), but want to avoid keep getting prompts on whether a book should be exported or not.
    //
    // Also, we use a vector here instead of map to make it more intuitive in preserving the ordering.
    books: Vec<ExportItem>,
}

impl ExportIndex {
    fn load_or_default(path: &PathBuf) -> Result<ExportIndex> {
        if !path.exists() {
            return Ok(ExportIndex { books: vec![] });
        }

        let index_str = fs::read_to_string(path)?;
        let index: ExportIndex = toml::from_str(&index_str)?;

        Ok(index)
    }

    fn save(&self, path: &PathBuf) -> Result<()> {
        let index_str = toml::to_string(self)?;
        let mut file = fs::File::create(path)?;
        write!(file, "{}", index_str)?; // we don't use buffered writer since we just write everything at once
        Ok(())
    }

    // This function checks the book against the index. It returns a boolean that indicates whether the
    // book data (e.g., annotations) should be further fetched or not.
    //
    // Note that upon checking for the existence of a book, the function only looks up information based
    // on the book's ASIN.
    //
    // The function involves some user interaction via stdin/out to prompt users whether they want to fetch
    // the latest book data and/or update the index.
    //
    // WARN: They may be some inconsistencies between the exported markdown (if any) and the index file if a
    //       user decides to update the index but not fetch the book. However, this could be useful to avoid
    //       keep getting prompts.
    fn check_book(&mut self, book: &Book) -> bool {
        // Generate the current time in case we want to update the index
        let local = Local::now();
        let current_datetime = local.to_rfc2822(); // example: "Wed, 26 Jan 2022 21:15:25 +0800"

        // WARN: This could be problematic if someone tampers with the index file manually and adds a book
        //       with a duplicate ASIN. However, we ignore it now since it is not an expected behavior.
        for indexed_book in self.books.iter_mut() {
            // Skip if the ASIN is different
            if indexed_book.info.asin != book.asin {
                continue;
            }

            // Update the checked field
            if indexed_book.checked {
                // Indication of a potentially duplicate ASIN. Very unlikely, but checking just in case.
                warn!("A book is checked twice: {:?}", indexed_book.info);
            }
            indexed_book.checked = true;

            // Found a matching ASIN

            // If the metadata stays the same, then we could safely assume that a book has not been modified
            // since the last fetch. By "modify", we refer to the `last_opened_date` in the book, which would
            // change if we open the book (e.g., to read again or add new annotations).
            //
            // WARN: This could potentially has some issues since the "last_opened_date" only includes the
            //       exact date, but not the time. Hence, if someone fetches a book in the morning and modifies
            //       it in the evening, we may not be able to detect the changes. To handle this case, a user
            //       can simply reopen the book on the next day, which will trigger the prompt again, or perhaps
            //       update some metadata in the index which could trigger a fetch prompt.
            if &indexed_book.info == book {
                return false;
            }

            // The book metadata has been changed. In most cases, this is probably because a user re-opens the book.
            println!("");
            println!("Found a book that has been modified:");
            println!("- Old: {:?}", indexed_book.info);
            println!("- New: {:?}", book);
            println!("");

            // Ask the user first whether they want to fetch the updated annotations

            // If yes, then we will automatically update the index to reflect the latest metadata
            if prompt_user("Do you want to fetch the latest data for this book?") {
                indexed_book.info = book.clone();
                indexed_book.last_updated_time = current_datetime;
                return true;
            }

            // If no, then we need to ask users whether they want to update the metadata
            if prompt_user("Do you want to update the indexed metadata?") {
                indexed_book.info = book.clone();
                indexed_book.last_updated_time = current_datetime;
            }

            return false;
        }

        // A book couldn't be found on the index
        //
        // Note that if we decide to add a new book to the index, it will always be appended to the back of the
        // list. Maybe can consider to make the list sorted based on the last updated time in the future.

        println!("");
        println!("Unable to find information about the following book in the index:");
        println!("  {:?}", book);
        println!("");

        // Ask the user first whether they want to fetch the book

        // Prepare the export item in case we need to update the index
        let item = ExportItem {
            info: book.clone(),
            last_updated_time: current_datetime,
            checked: true, // Note that we consider the book to have been checked here
        };

        // If yes, we will automatically update the index as well
        if prompt_user("Do you want to fetch the book data?") {
            self.books.push(item);
            return true;
        }

        // If no, we ask the user whether they want to update the index.
        // This could be useful if they want to avoid keep getting prompts for a book that has not
        // been opened again.
        if prompt_user("Do you want to add the book to the index?") {
            self.books.push(item);
        }

        return false;
    }

    // Helper function to write a warning log if some books are left unchecked
    fn warn_unchecked_books(&self) {
        for book in &self.books {
            if !book.checked {
                warn!("Book {:?} has not been checked", book.info);
            }
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
struct ExportItem {
    // Note that we use a string here instead of a date/time object for simplicity
    last_updated_time: String,

    // Helper variable to help us keep track whether a book has been checked or not in the index.
    //
    // The way the export function works is that it will first retrieve the list of all available books in the
    // Kindle library. Afterward, it will check against the export index and prompt users if it encounters
    // a book that couldn't be found in the index or has a different metadata. This variable helps us to figure
    // out in case the book that is somehow missing from the Kindle library, and hence unchecked.
    //
    // Note that we won't serialize/deserialize this value to the index. It is only for internal tracking to
    // potentially log some warnings. The default value is false whenever we just parse an export index from
    // its file representation.
    #[serde(skip_serializing, skip_deserializing, default)]
    checked: bool,

    // Note that we put this information as the last field because TOML requires all non-tables to be listed first
    info: Book,
}

// Helper function to prompt user response for a yes or no question.
fn prompt_user(question: &str) -> bool {
    loop {
        let mut input = String::new();
        print!("{} (y/n): ", question);
        let _ = io::stdout().flush();
        io::stdin()
            .read_line(&mut input)
            .expect("error reading from stdin");

        input = input.trim().to_lowercase(); // convert to lowercase for convenience
        if input == "y" {
            return true;
        } else if input == "n" {
            return false;
        } else {
            // We don't need to flush the output here since it will be flushed along with the next loop.
            println!("Unable to parse input. Please response using the provided options (case-insensitive).")
        }
    }
}
