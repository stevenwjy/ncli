use anyhow::{anyhow, Result};
use fantoccini::{Client as WebClient, ClientBuilder as WebClientBuilder, Locator};
use serde_json::json;

use crate::kindle::annotation::AnnotationList;
use crate::kindle::book::{Book, BookLibrary};

// The notebook URL is useful to fetch the list of books in the library.
const ROOT_URL: &str = "https://read.amazon.com/notebook";

pub struct ClientOpts {
    pub headless: bool,
    pub email: String,
    pub password: String,
}

pub struct Client {
    opts: ClientOpts,

    // The kindle client currently wraps around the webdriver client, which is used to interact with the kindle
    // page since they don't really provide public APIs.
    client: WebClient,
}

impl Client {
    pub async fn new(opts: ClientOpts) -> Client {
        let mut client = WebClientBuilder::native();

        if opts.headless {
            let mut caps = serde_json::Map::new();
            caps.insert(
                String::from("moz:firefoxOptions"),
                json!({"args": ["-headless"]}),
            );

            client.capabilities(caps);
        }

        let client = client
            .connect("http://localhost:4444")
            .await
            .expect("failed to connect to WebDriver");

        Client { opts, client }
    }

    pub async fn get_books(&mut self) -> Result<BookLibrary> {
        // Go to the notebook website
        self.client.goto(ROOT_URL).await?;

        // If we don't end up at the root URL, it means that we need to login first
        let cur_url = self.client.current_url().await?;
        if !cur_url.as_str().starts_with(ROOT_URL) {
            self.authenticate().await?;
        }

        // If we still don't end up at the root URL, maybe we encountered an error
        let cur_url = self.client.current_url().await?;
        if !cur_url.as_str().starts_with(ROOT_URL) {
            return Err(anyhow!("unable to sign in"));
        }

        let html = self
            .client
            .wait()
            .for_element(Locator::Id("kp-notebook-library"))
            .await?
            .html(false)
            .await?;

        return BookLibrary::from_html(&html);
    }

    pub async fn get_annotations(&mut self, book: &Book) -> Result<AnnotationList> {
        // We hardcode the string here since format can only work with a string literal
        let url = format!(
            "https://read.amazon.com/kp/notebook?captcha_verified=1&asin={}&contentLimitState=&",
            book.asin
        );

        // Go to the annotation url
        //
        // Note that we assume that the authentication has been performed successfully before.
        self.client.goto(&url).await?;

        let html = self
            .client
            .wait()
            .for_element(Locator::Id("kp-notebook-annotations"))
            .await?
            .html(false)
            .await?;

        return AnnotationList::from_html(&html);
    }

    pub async fn close(&mut self) -> Result<()> {
        let _ = self.client.close().await?;
        Ok(())
    }

    // The authentication function is currently supposed to only be used internally, since it involves some
    // redirection upon successful login.
    async fn authenticate(&mut self) -> Result<()> {
        let mut form = self
            .client
            .form(Locator::XPath(r#"//*[@name="signIn"]"#))
            .await?;
        form.set_by_name("email", &self.opts.email)
            .await?
            .set_by_name("password", &self.opts.password)
            .await?
            .submit()
            .await?;

        Ok(())
    }
}
