use anyhow::Result;
use scraper::{Html, Selector};
use serde::{Deserialize, Serialize};

#[derive(Debug, Eq, PartialEq)]
pub struct BookLibrary {
    pub books: Vec<Book>,
}

impl BookLibrary {
    pub fn from_html(html: &str) -> Result<BookLibrary> {
        let fragment = Html::parse_fragment(html);
        let selector = Selector::parse(r#"div.kp-notebook-library-each-book"#).unwrap();

        let mut books = vec![];
        for element in fragment.select(&selector) {
            books.push(Book::from_html(element.html().as_str())?);
        }

        Ok(BookLibrary { books })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Book {
    // ASIN: Amazon Standard Identification Number
    //
    // Note that every book is supposed to have a unique ASIN, and hence it is actually sufficient to compare the
    // "equality" of two books using their ASIN. However, note that the derived implementation for `Eq` and `PartialEq`
    // for this book object will use all of the fields because we sometimes want to cross-check the associated
    // metadata as well (e.g., last opened date).
    pub asin: String,

    // Title of the book
    pub title: String,

    // Subtitle of the book
    //
    // Note that some books may not have any subtitles, and hence we skip serializing this field and set the value
    // to be `None` if no associated value could be found upon deserialization.
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub subtitle: Option<String>,

    // Author of the book
    //
    // Note that there could be more than one authors for a book, but in Kindle they will be concatenated together
    // as a single string.
    pub author: String,

    // URL to the book image
    pub image_url: String,

    // The last time a book is opened on Kindle.
    //
    // Note that we simply record the string representation that is chosen by Kindle here. It will typically be
    // in the following format: "Wednesday January 26, 2022".
    pub last_opened_date: String,
}

impl Book {
    pub fn from_html(html: &str) -> Result<Book> {
        let fragment = Html::parse_fragment(html);

        // Retrieve the Amazon Standard Identification Number (ASIN)
        //
        // We need this value if we want to fetch other information about the book from Amazon (e.g., highlights).
        let selector = Selector::parse("div").unwrap();
        let asin = fragment
            .select(&selector)
            .next()
            .unwrap()
            .value()
            .attr("id")
            .unwrap()
            .to_string();

        // Retrieve the book title
        let selector = Selector::parse("h2").unwrap();
        let full_title = fragment.select(&selector).next().unwrap().inner_html();
        // Note that some books have the following format for the title: "<title>: <subtitle>".
        // Hence, we want to identify the subtitle and separate it from the main title if there is any. The reason
        // is because we want to save a book only based on its title as the file name.
        let title_parts: Vec<&str> = full_title.splitn(2, ":").collect();
        let title = String::from(title_parts[0].trim());
        let subtitle = if title_parts.len() > 1 {
            Some(title_parts[1].trim().into())
        } else {
            None
        };

        // Retrieve the author
        //
        // In the website, the author is written in the following format: "By: <author>". Hence, we need to remove
        // the "By: " prefix.
        let selector = Selector::parse("p").unwrap();
        let author = fragment.select(&selector).next().unwrap().inner_html();
        let author_parts: Vec<&str> = author.splitn(2, ":").collect();
        let author = String::from(author_parts[1].trim());

        // Retrieve the image url
        //
        // Note that the url will be using Amazon CDN and it is not guaranteed for long time use as they could
        // change over time.
        let selector = Selector::parse("img").unwrap();
        let image_url = fragment
            .select(&selector)
            .next()
            .unwrap()
            .value()
            .attr("src")
            .unwrap()
            .to_string();

        // Retrieve the last opened date
        //
        // Note that we keep it as a string, since this value is probably not that useful given that we may
        // occasionally open a book, but not adding any new annotations.
        let last_opened_date_selector = Selector::parse("input").unwrap();
        let last_opened_date = fragment
            .select(&last_opened_date_selector)
            .next()
            .unwrap()
            .value()
            .attr("value")
            .unwrap()
            .to_string();

        // Construct the book object based on all the information that we have
        Ok(Book {
            asin,
            title,
            subtitle,
            author,
            image_url,
            last_opened_date,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{Book, BookLibrary};

    // The following sample HTML is taken from the original structure of Kindle notebook with some modifications
    // on identification values to avoid potential security issues. Hence, the values in this HTML string are actually
    // invalid and should not be considered to have any meaning.
    const SAMPLE_HTML: &str = r#"
        <div id="kp-notebook-library" class="a-row">
            <div id="ABCDEFGHIJ" class="a-row kp-notebook-library-each-book a-color-base-background">
                <span class="a-declarative" data-action="get-annotations-for-asin" data-csa-c-type="widget" data-csa-c-func-deps="aui-da-get-annotations-for-asin" data-get-annotations-for-asin="{&quot;asin&quot;:&quot;ABCDEFGHIJ&quot;}" data-csa-c-id="abc123-123abc-abcdef-fedcba">
                    <a class="a-link-normal a-text-normal" href="javascript:void(0);">
                        <div class="a-row">
                            <div class="a-column a-span4 a-push4 a-spacing-medium a-spacing-top-medium">
                                <img alt="" src="https://m.media-amazon.com/images/I/12ab34ef56g._XY789.jpg" class="kp-notebook-cover-image kp-notebook-cover-image-border">
                            </div>
                        </div>
                        <h2 class="a-size-base a-color-base a-text-center kp-notebook-searchable a-text-bold">
                            Title A: Subtitle A
                        </h2>
                        <p class="a-spacing-base a-spacing-top-mini a-text-center a-size-base a-color-secondary kp-notebook-searchable">
                            By: Author A
                        </p>
                    </a>
                </span>
                <input type="hidden" name="" value="Sunday January 30, 2022" id="kp-notebook-annotated-date-ABCDEFGHIJ">
            </div>
            <div id="ABCDEFGHIK" class="a-row kp-notebook-library-each-book">
                <span class="a-declarative" data-action="get-annotations-for-asin" data-csa-c-type="widget" data-csa-c-func-deps="aui-da-get-annotations-for-asin" data-get-annotations-for-asin="{&quot;asin&quot;:&quot;ABCDEFGHIK&quot;}" data-csa-c-id="abc123-123abc-abcdef-fedcbx">
                    <a class="a-link-normal a-text-normal" href="javascript:void(0);">
                        <div class="a-row">
                            <div class="a-column a-span4 a-push4 a-spacing-medium a-spacing-top-medium">
                                <img alt="" src="https://m.media-amazon.com/images/I/12ab34ef56g._XY987.jpg" class="kp-notebook-cover-image kp-notebook-cover-image-border">
                            </div>
                        </div>
                        <h2 class="a-size-base a-color-base a-text-center kp-notebook-searchable a-text-bold">
                            Title B
                        </h2>
                        <p class="a-spacing-base a-spacing-top-mini a-text-center a-size-base a-color-secondary kp-notebook-searchable">
                            By: Author B
                        </p>
                    </a>
                </span>
                <input type="hidden" name="" value="Sunday January 30, 2022" id="kp-notebook-annotated-date-ABCDEFGHIK">
            </div>    
            <input type="hidden" name="" class="kp-notebook-library-next-page-start">
        </div>
    "#;

    #[test]
    fn parse_library() {
        let parsed_library = BookLibrary::from_html(SAMPLE_HTML).expect("unable to parse html");
        let expected_library = BookLibrary {
            books: vec![
                Book {
                    asin: "ABCDEFGHIJ".into(),
                    title: "Title A".into(),
                    subtitle: Some("Subtitle A".into()),
                    author: "Author A".into(),
                    image_url: "https://m.media-amazon.com/images/I/12ab34ef56g._XY789.jpg".into(),
                    last_opened_date: "Sunday January 30, 2022".into(),
                },
                Book {
                    asin: "ABCDEFGHIK".into(),
                    title: "Title B".into(),
                    subtitle: None,
                    author: "Author B".into(),
                    image_url: "https://m.media-amazon.com/images/I/12ab34ef56g._XY987.jpg".into(),
                    last_opened_date: "Sunday January 30, 2022".into(),
                },
            ],
        };

        assert_eq!(parsed_library, expected_library);
    }
}
