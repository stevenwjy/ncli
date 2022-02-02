use anyhow::Result;
use scraper::{Html, Selector};

#[derive(Debug, Eq, PartialEq)]
pub struct AnnotationList {
    pub annotations: Vec<Annotation>,
}

impl AnnotationList {
    pub fn from_html(html: &str) -> Result<AnnotationList> {
        let fragment = Html::parse_fragment(html);
        let selector = Selector::parse(r#"div.kp-notebook-row-separator"#).unwrap();

        let mut annotations = vec![];
        for element in fragment.select(&selector) {
            annotations.push(Annotation::from_html(element.html().as_str())?);
        }

        Ok(AnnotationList { annotations })
    }
}

#[derive(Debug, Eq, PartialEq)]
pub struct Annotation {
    // Note that we flatten the structure for highlight and note here, since an annotation in Kindle could be
    // in the form of a highlight, a note, or both.
    pub highlight: Option<String>,
    pub highlight_color: Option<String>,
    pub note: Option<String>,

    // Note that not all books have page number, hence we make it optional here.
    pub page: Option<u32>,

    // The location is useful if we want to perform a lookup for this specific annotation in the book.
    pub location: u32,
}

impl Annotation {
    pub fn from_html(html: &str) -> Result<Annotation> {
        let fragment = Html::parse_fragment(html);

        let mut highlight = None;
        let mut highlight_color = None;
        let mut note = None;
        let mut page = None;

        // Retrieve the highlight
        //
        // Note that it is possible that the annotation does not have any highlight, but has a note.
        let selector = Selector::parse("span#highlight").unwrap();
        if let Some(highlight_ref) = fragment.select(&selector).next() {
            // The annotation contains a highlight
            highlight = Some(highlight_ref.inner_html());

            // Retrieve the highlight header
            //
            // The header will be one of the following formats:
            // 1. "<color> annotation | Page: <page>" if there's a page number
            // 2. "<color> annotation | Location: <location>" if there's no page number
            //
            // However, since we can always get the location from another field, we won't retrieve the location
            // for the second case.
            let selector = Selector::parse("span#annotationHighlightHeader").unwrap();
            let header = fragment.select(&selector).next().unwrap().inner_html();
            let header_parts: Vec<&str> = header.splitn(2, "|").collect();
            let color_parts: Vec<&str> = header_parts[0].trim().splitn(2, " ").collect();
            let page_parts: Vec<&str> = header_parts[1].trim().splitn(2, ":&nbsp;").collect();

            // We can retrieve highlight color and potentially the page number here
            highlight_color = Some(color_parts[0].to_string());
            if page_parts[0] == "Page" {
                page = Some(page_parts[1].parse::<u32>()?);
            }
        }

        // Retrieve the note
        //
        // Note that the Kindle notebook page is a bit weird since it will always have the note element.
        // In order to find out about its existence, we need to check the length.
        let selector = Selector::parse("span#note").unwrap();
        let note_str = fragment.select(&selector).next().unwrap().inner_html();
        if note_str.len() > 0 {
            note = Some(note_str);

            // If there is no highlight, we need to check the page number using the note header
            if highlight.is_none() {
                // Similar with the highlight header, it will be one of the following formats:
                // 1. "Note | Page: <page>" if there's a page number
                // 2. "Note | Location: <location>" if there's no page number
                //
                // Only the first case is useful.
                let selector = Selector::parse("span#annotationNoteHeader").unwrap();
                let header = fragment.select(&selector).next().unwrap().inner_html();
                let header_parts: Vec<&str> = header.splitn(2, "|").collect();
                let page_parts: Vec<&str> = header_parts[1].trim().splitn(2, ":&nbsp;").collect();

                if page_parts[0] == "Page" {
                    page = Some(page_parts[1].parse::<u32>()?);
                }
            }
        }

        // Retrieve the location
        let selector = Selector::parse("input#kp-annotation-location").unwrap();
        let location = fragment
            .select(&selector)
            .next()
            .unwrap()
            .value()
            .attr("value")
            .unwrap()
            .parse::<u32>()?;

        Ok(Annotation {
            highlight,
            highlight_color,
            note,
            page,
            location,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{Annotation, AnnotationList};

    // The following sample HTML is taken from the original structure of Kindle notebook with some modifications
    // on identification values to avoid potential security issues. Hence, the values in this HTML string are actually
    // invalid and should not be considered to have any meaning.
    const SAMPLE_HTML: &str = r#"
        <div id="kp-notebook-annotations" class="a-row"><input type="hidden" name="" value="REDACTED" class="kp-notebook-content-limit-state"><input type="hidden" name="" class="kp-notebook-annotations-next-page-start">
            <div id="REDACTED" class="a-row a-spacing-base">
                <div class="a-column a-span10 kp-notebook-row-separator">
                    <div class="a-row"><input type="hidden" name="" value="1024" id="kp-annotation-location">
                        <div class="a-column a-span8">
                            <span id="annotationHighlightHeader" class="a-size-small a-color-secondary kp-notebook-selectable kp-notebook-metadata">Yellow highlight | Page:&nbsp;32</span>
                            <span id="annotationNoteHeader" class="a-size-small a-color-secondary aok-hidden kp-notebook-selectable kp-notebook-metadata">Note | Page:&nbsp;32</span>
                        </div>
                        <div class="a-column a-span4 a-text-right a-span-last"><span class="a-declarative" data-action="a-popover" data-csa-c-type="widget" data-csa-c-func-deps="aui-da-a-popover" data-a-popover="{&quot;closeButton&quot;:&quot;false&quot;,&quot;closeButtonLabel&quot;:&quot;Close&quot;,&quot;activate&quot;:&quot;onclick&quot;,&quot;width&quot;:&quot;200&quot;,&quot;name&quot;:&quot;optionsPopover&quot;,&quot;position&quot;:&quot;triggerVerticalAlignLeft&quot;,&quot;popoverLabel&quot;:&quot;Options for annotations at Page 32&quot;}" id="popover-REDACTED-action"><a id="popover-REDACTED" href="javascript:void(0)" role="button" class="a-popover-trigger a-declarative">Options<i class="a-icon a-icon-popover"></i></a></span></div>
                    </div>
                    <div class="a-row a-spacing-top-medium">
                        <div class="a-column a-span10 a-spacing-small kp-notebook-print-override">
                            <div id="highlight-REDACTED" class="a-row kp-notebook-highlight kp-notebook-selectable kp-notebook-highlight-yellow"><span id="highlight" class="a-size-base-plus a-color-base">Highlight</span>
                                <div></div>
                            </div>
                            <div id="note-" class="a-row a-spacing-top-base kp-notebook-note aok-hidden kp-notebook-selectable"><span id="note-label" class="a-size-small a-color-secondary">Note:<span class="a-letter-space"></span></span><span id="note" class="a-size-base-plus a-color-base"></span></div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="REDACTED" class="a-row a-spacing-base">
                <div class="a-column a-span10 kp-notebook-row-separator">
                    <div class="a-row"><input type="hidden" name="" value="2048" id="kp-annotation-location">
                        <div class="a-column a-span8">
                            <span id="annotationNoteHeader" class="a-size-small a-color-secondary kp-notebook-selectable kp-notebook-metadata">Note | Page:&nbsp;64</span></div>
                        <div class="a-column a-span4 a-text-right a-span-last"><span class="a-declarative" data-action="a-popover" data-csa-c-type="widget" data-csa-c-func-deps="aui-da-a-popover" data-a-popover="{&quot;closeButton&quot;:&quot;false&quot;,&quot;closeButtonLabel&quot;:&quot;Close&quot;,&quot;activate&quot;:&quot;onclick&quot;,&quot;width&quot;:&quot;200&quot;,&quot;name&quot;:&quot;optionsPopover&quot;,&quot;position&quot;:&quot;triggerVerticalAlignLeft&quot;,&quot;popoverLabel&quot;:&quot;Options for annotations at Page 64&quot;}" id="popover-REDACTED-action"><a id="popover-REDACTED" href="javascript:void(0)" role="button" class="a-popover-trigger a-declarative">Options<i class="a-icon a-icon-popover"></i></a></span></div>
                    </div>
                    <div class="a-row a-spacing-top-medium">
                        <div class="a-column a-span10 a-spacing-small kp-notebook-print-override">
                            <div id="note-REDACTED" class="a-row kp-notebook-note kp-notebook-selectable"><span id="note" class="a-size-base-plus a-color-base">Note</span></div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="REDACTED" class="a-row a-spacing-base">
                <div class="a-column a-span10 kp-notebook-row-separator">
                    <div class="a-row"><input type="hidden" name="" value="4096" id="kp-annotation-location">
                        <div class="a-column a-span8">
                            <span id="annotationHighlightHeader" class="a-size-small a-color-secondary kp-notebook-selectable kp-notebook-metadata">Yellow highlight | Page:&nbsp;128</span>
                            <span id="annotationNoteHeader" class="a-size-small a-color-secondary aok-hidden kp-notebook-selectable kp-notebook-metadata">Note | Page:&nbsp;128</span>
                        </div>
                        <div class="a-column a-span4 a-text-right a-span-last"><span class="a-declarative" data-action="a-popover" data-csa-c-type="widget" data-csa-c-func-deps="aui-da-a-popover" data-a-popover="{&quot;closeButton&quot;:&quot;false&quot;,&quot;closeButtonLabel&quot;:&quot;Close&quot;,&quot;activate&quot;:&quot;onclick&quot;,&quot;width&quot;:&quot;200&quot;,&quot;name&quot;:&quot;optionsPopover&quot;,&quot;position&quot;:&quot;triggerVerticalAlignLeft&quot;,&quot;popoverLabel&quot;:&quot;Options for annotations at Page 128&quot;}" id="popover-REDACTED-action"><a id="popover-REDACTED" href="javascript:void(0)" role="button" class="a-popover-trigger a-declarative">Options<i class="a-icon a-icon-popover"></i></a></span></div>
                    </div>
                    <div class="a-row a-spacing-top-medium">
                        <div class="a-column a-span10 a-spacing-small kp-notebook-print-override">
                            <div id="highlight-REDACTED" class="a-row kp-notebook-highlight kp-notebook-selectable kp-notebook-highlight-yellow"><span id="highlight" class="a-size-base-plus a-color-base">Highlight</span>
                                <div></div>
                            </div>
                            <div id="note-REDACTED" class="a-row a-spacing-top-base kp-notebook-note kp-notebook-selectable"><span id="note-label" class="a-size-small a-color-secondary">Note:<span class="a-letter-space"></span></span><span id="note" class="a-size-base-plus a-color-base">Note</span></div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="empty-annotations-pane" class="a-row aok-hidden">
                <div class="a-column a-span6 a-push3">
                    <div class="a-box a-spacing-top-extra-large a-box-normal a-color-base-background a-text-center">
                        <div class="a-box-inner">
                            <div class="a-row a-spacing-large a-spacing-top-medium">
                                <div class="a-column a-span4 a-push4">
                                    <img alt="" src="img/Note_icon.png" class="kp-notebook-cover-image" height="44">
                                </div>
                            </div>
                            <p class="a-spacing-medium a-size-medium a-text-bold"> Would you like to take some notes?</p>
                            <span>You haven’t created any notes for this book yet. You can add or remove bookmarks, highlights, and notes at any location in a Kindle book.</span>
                            <div class="a-row a-spacing-extra-large a-spacing-top-medium"><a class="a-link-emphasis" target="_blank" rel="noopener" href="https://www.amazon.com/b/?node=11627044011&amp;ref=k4w_ms_ynh_empty"> Learn more about notes and highlights</a></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    "#;

    #[test]
    fn parse_library() {
        let parsed_list = AnnotationList::from_html(SAMPLE_HTML).expect("unable to parse html");
        let expected_list = AnnotationList {
            annotations: vec![
                // Only highlight
                Annotation {
                    highlight: Some("Highlight".into()),
                    highlight_color: Some("Yellow".into()),
                    note: None,
                    page: Some(32),
                    location: 1024,
                },
                // Only note
                Annotation {
                    highlight: None,
                    highlight_color: None,
                    note: Some("Note".into()),
                    page: Some(64),
                    location: 2048,
                },
                // Highlight and note
                Annotation {
                    highlight: Some("Highlight".into()),
                    highlight_color: Some("Yellow".into()),
                    note: Some("Note".into()),
                    page: Some(128),
                    location: 4096,
                },
            ],
        };

        assert_eq!(parsed_list, expected_list);
    }
}
