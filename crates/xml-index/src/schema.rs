//! The schema file: which elements become rows of which tables, and what each column holds.
//!
//! ```toml
//! format = 1
//! name = "example"
//!
//! [[table]]
//! name = "thing"
//! match = ["root/things/thing", "**/innerList/li"]   # element paths from the root; * one part, ** any number
//! require = ["def"]                                  # rows without a value here are not written
//! indexes = ["def"]
//! [[table.column]]
//! name = "def"
//! path = "def"                                       # text of a child element, relative to the matched one
//! [[table.column]]
//! name = "class"
//! attr = "Class"                                     # an attribute of the matched element (or of `path`)
//! [[table.column]]
//! name = "holder"
//! parent = "thing"                                   # the nearest enclosing row of that table
//! [[table.column]]
//! name = "position"
//! index = true                                       # place among same-named siblings, from 0
//!
//! [[view]]
//! name = "big_things"
//! sql = "SELECT * FROM thing WHERE stack > 100"
//! ```
//!
//! Column types: text (the default), int, real, bool (True/False as 1/0), and ivec3, which reads "(x, y, z)"
//! into three integer columns named <name>_x, <name>_y and <name>_z. A value that does not parse as its type is
//! kept as text.

use serde::Deserialize;
use std::collections::HashSet;

pub const FORMAT: u32 = 1;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Schema {
    pub format: u32,
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default, rename = "table")]
    pub tables: Vec<TableSpec>,
    #[serde(default, rename = "view")]
    pub views: Vec<ViewSpec>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TableSpec {
    pub name: String,
    #[serde(rename = "match")]
    pub patterns: Vec<String>,
    #[serde(default)]
    pub require: Vec<String>,
    #[serde(default)]
    pub indexes: Vec<String>,
    #[serde(default, rename = "column")]
    pub columns: Vec<ColumnSpec>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ColumnSpec {
    pub name: String,
    #[serde(default)]
    pub path: Option<String>,
    #[serde(default)]
    pub attr: Option<String>,
    #[serde(default)]
    pub parent: Option<String>,
    #[serde(default)]
    pub index: bool,
    #[serde(default, rename = "type")]
    pub kind: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ViewSpec {
    pub name: String,
    pub sql: String,
}

/// Columns every table has, which a schema may not define again.
pub const RESERVED: [&str; 2] = ["id", "path_id"];
/// Tables the indexer always writes.
pub const BUILT_IN_TABLES: [&str; 2] = ["element_path", "meta"];

fn valid_identifier(name: &str) -> bool {
    let mut chars = name.chars();
    matches!(chars.next(), Some(c) if c.is_ascii_lowercase() || c == '_')
        && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

impl Schema {
    pub fn parse(text: &str) -> Result<Schema, String> {
        let schema: Schema = toml::from_str(text).map_err(|e| format!("the schema is not valid TOML: {e}"))?;
        schema.validate()?;
        Ok(schema)
    }

    fn validate(&self) -> Result<(), String> {
        if self.format != FORMAT {
            return Err(format!("schema format {} is not supported (this indexer reads format {FORMAT})", self.format));
        }
        let mut names = HashSet::new();
        for table in &self.tables {
            if !valid_identifier(&table.name) {
                return Err(format!("table name \"{}\" must be lower-case letters, digits and _", table.name));
            }
            if BUILT_IN_TABLES.contains(&table.name.as_str()) || !names.insert(table.name.as_str()) {
                return Err(format!("table name \"{}\" is used twice or is built in", table.name));
            }
            if table.patterns.is_empty() {
                return Err(format!(
                    "table \"{}\" matches no elements: give it at least one match pattern",
                    table.name
                ));
            }
        }
        for view in &self.views {
            if !valid_identifier(&view.name) || !names.insert(view.name.as_str()) {
                return Err(format!("view name \"{}\" is not a valid, unused name", view.name));
            }
        }
        for table in &self.tables {
            let mut columns = HashSet::new();
            for column in &table.columns {
                let label = format!("column \"{}\" of table \"{}\"", column.name, table.name);
                if !valid_identifier(&column.name) || RESERVED.contains(&column.name.as_str()) {
                    return Err(format!(
                        "{label}: the name must be lower-case letters, digits and _, and not id or path_id"
                    ));
                }
                if !columns.insert(column.name.as_str()) {
                    return Err(format!("{label} is defined twice"));
                }
                let sources = usize::from(column.path.is_some() || column.attr.is_some())
                    + usize::from(column.parent.is_some())
                    + usize::from(column.index);
                if sources != 1 {
                    return Err(format!("{label} needs exactly one of path/attr, parent or index"));
                }
                if let Some(parent) = &column.parent {
                    if !self.tables.iter().any(|t| &t.name == parent) {
                        return Err(format!(
                            "{label} names a parent table \"{parent}\" that the schema does not define"
                        ));
                    }
                }
                match column.kind.as_deref() {
                    None | Some("text" | "int" | "real" | "bool" | "ivec3") => {}
                    Some(other) => return Err(format!("{label} has an unknown type \"{other}\"")),
                }
                if column.kind.as_deref() == Some("ivec3") && (column.parent.is_some() || column.index) {
                    return Err(format!("{label}: ivec3 reads text, so it needs path or attr"));
                }
            }
            for name in table.require.iter().chain(&table.indexes) {
                if !columns.contains(name.as_str()) && !RESERVED.contains(&name.as_str()) {
                    return Err(format!(
                        "table \"{}\" requires or indexes a column \"{name}\" it does not define",
                        table.name
                    ));
                }
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const GOOD: &str = r#"
        format = 1
        name = "t"
        [[table]]
        name = "thing"
        match = ["a/b"]
        require = ["def"]
        [[table.column]]
        name = "def"
        path = "def"
        [[table.column]]
        name = "holder"
        parent = "thing"
        [[view]]
        name = "v"
        sql = "SELECT 1"
    "#;

    #[test]
    fn a_good_schema_parses() {
        let schema = Schema::parse(GOOD).unwrap();
        assert_eq!(schema.tables[0].columns.len(), 2);
        assert_eq!(schema.views[0].name, "v");
    }

    #[test]
    fn unknown_keys_are_refused() {
        let text = GOOD.replace("require = [\"def\"]", "requires = [\"def\"]");
        assert!(Schema::parse(&text).unwrap_err().contains("not valid TOML"));
    }

    #[test]
    fn names_must_be_plain_identifiers() {
        let text = GOOD.replace("name = \"thing\"", "name = \"thing; DROP\"");
        assert!(Schema::parse(&text).is_err());
    }

    #[test]
    fn a_column_needs_exactly_one_source() {
        let text = GOOD.replace("parent = \"thing\"", "parent = \"thing\"\n        index = true");
        assert!(Schema::parse(&text).unwrap_err().contains("exactly one"));
    }

    #[test]
    fn parents_must_exist_and_types_must_be_known() {
        assert!(Schema::parse(&GOOD.replace("parent = \"thing\"", "parent = \"nope\"")).is_err());
        let text = GOOD.replace("path = \"def\"", "path = \"def\"\n        type = \"float\"");
        assert!(Schema::parse(&text).unwrap_err().contains("unknown type"));
    }

    #[test]
    fn reserved_and_built_in_names_are_refused() {
        assert!(Schema::parse(&GOOD.replace("name = \"def\"", "name = \"id\"")).is_err());
        assert!(Schema::parse(&GOOD.replace("name = \"thing\"", "name = \"meta\"")).is_err());
    }

    #[test]
    fn required_columns_must_be_defined() {
        assert!(Schema::parse(&GOOD.replace("require = [\"def\"]", "require = [\"stack\"]")).is_err());
    }
}
