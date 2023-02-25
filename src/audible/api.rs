use serde::{Deserialize, Serialize};

// ---
// Chapters
// ---

#[derive(Debug, Deserialize, Serialize)]
pub struct GetChaptersResponse {
    pub content_metadata: ContentMetadata,
    pub response_groups: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct ContentMetadata {
    pub chapter_info: ChapterInfo,
    pub content_reference: ContentReference,
    pub last_position_heard: LastPositionHeard,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct ChapterInfo {
    #[serde(rename = "brandIntroDurationMs")]
    pub brand_intro_duration_ms: u32,

    #[serde(rename = "brandOutroDurationMs")]
    pub brand_outro_duration_ms: u32,

    pub chapters: Vec<Chapter>,

    pub is_accurate: bool,
    pub runtime_length_ms: u32,
    pub runtime_length_sec: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Chapter {
    // Title of the chapter
    pub title: String,

    // Metadata
    pub length_ms: u32,
    pub start_offset_ms: u32,
    pub start_offset_sec: u32,

    // Sub-chapters
    pub chapters: Option<Vec<Chapter>>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct ContentReference {
    pub acr: String,
    pub asin: String,
    pub codec: String,
    pub content_format: String,
    pub content_size_in_bytes: u64,
    pub file_version: String,
    pub marketplace: String,
    pub sku: String,
    pub tempo: String,
    pub version: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct LastPositionHeard {
    // Possible values:
    // - "Exists"
    // - "DoesNotExist"
    pub status: String,

    // Will be None if the status is "DoesNotExist"
    pub last_updated: Option<String>,
    pub position_ms: Option<u32>,
}

// ---
// Annotations
// ---

#[derive(Debug, Deserialize, Serialize)]
pub struct GetAnnotationsResponse {
    pub md5: String,
    pub payload: GetAnnotationsPayload,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct GetAnnotationsPayload {
    #[serde(rename = "type")]
    pub content_type: String,

    pub records: Vec<Record>,

    pub acr: Option<String>,
    pub key: String,
    pub guid: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Record {
    // Type of the annotation record.
    //
    // Possible values:
    // - "audible.last_heard"
    // - "audible.bookmark"
    // - "audible.clip"
    // - "audible.note"
    //
    // A single book is expected to only have one "audible.last_heard" record.
    //
    // Each bookmark is associated with exactly one clip, and each clip could have one note.
    // They are somehow separated into different records, but in the app there is only a single
    // option to add clip, which could optionally have some notes associated with it (like Kindle highlight).
    #[serde(rename = "type")]
    pub record_type: String,

    pub start_position: String,
    pub creation_time: String,

    // Only for bookmark, clip, and note.
    pub annotation_id: Option<String>,
    pub last_modification_time: Option<String>,

    // Only for clip.
    pub end_position: Option<String>,
    pub metadata: Option<RecordMetadata>,

    // Only for note.
    pub text: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct RecordMetadata {
    pub note: Option<String>,
    pub c_version: String,
}
