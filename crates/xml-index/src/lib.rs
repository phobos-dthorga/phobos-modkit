//! xml-index: streams a large XML file once into a SQLite index, driven by a schema file.
//!
//! Game knowledge lives in the schema files that game adapters ship; nothing here names a game.

pub mod index;
pub mod pattern;
pub mod schema;

pub use index::{Summary, build};
pub use schema::Schema;
