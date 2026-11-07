//! One streaming pass over an XML file: rows for the schema's tables, and a census of every element path.
//!
//! Every element gets a sequence number in document order; a row's `id` is its element's number, so `ORDER BY id`
//! is document order and parent columns point at the enclosing row's element. Memory stays proportional to the
//! depth of the document and the number of distinct element paths, not to its size.

use crate::pattern::Pattern;
use crate::schema::Schema;
use quick_xml::Reader;
use quick_xml::events::{BytesStart, Event};
use rusqlite::types::Value;
use rusqlite::{Connection, params_from_iter};
use std::collections::HashMap;
use std::io::BufRead;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Kind {
    Text,
    Int,
    Real,
    Bool,
    IVec3,
}

#[derive(Debug)]
enum Source {
    Text,
    Attr(String),
    Parent(usize),
    Index,
}

#[derive(Debug)]
struct Column {
    name: String,
    kind: Kind,
    source: Source,
}

#[derive(Debug)]
struct Table {
    name: String,
    patterns: Vec<Pattern>,
    columns: Vec<Column>,
    require: Vec<usize>,
    indexes: Vec<String>,
    /// Relative path ("" for the matched element itself) -> columns read from there (text or attribute).
    by_path: HashMap<String, Vec<usize>>,
    deepest: usize,
}

/// What one build wrote.
#[derive(Debug, Default)]
pub struct Summary {
    pub elements: u64,
    pub paths: usize,
    pub rows: Vec<(String, u64)>,
}

const NO_PARENT: u32 = u32::MAX;

#[derive(Default)]
struct Paths {
    names: Vec<String>,
    name_ids: HashMap<Vec<u8>, u32>,
    /// (parent path, name, depth) for each path id.
    nodes: Vec<(u32, u32, u32)>,
    node_ids: HashMap<(u32, u32), u32>,
    counts: Vec<u64>,
    /// Tables whose patterns match each path, worked out on first sight.
    matches: Vec<Option<Vec<usize>>>,
}

impl Paths {
    fn name(&mut self, raw: &[u8]) -> u32 {
        if let Some(&id) = self.name_ids.get(raw) {
            return id;
        }
        let id = self.names.len() as u32;
        self.names.push(String::from_utf8_lossy(raw).into_owned());
        self.name_ids.insert(raw.to_vec(), id);
        id
    }

    fn node(&mut self, parent: u32, name: u32) -> u32 {
        if let Some(&id) = self.node_ids.get(&(parent, name)) {
            return id;
        }
        let depth = if parent == NO_PARENT { 1 } else { self.nodes[parent as usize].2 + 1 };
        let id = self.nodes.len() as u32;
        self.nodes.push((parent, name, depth));
        self.node_ids.insert((parent, name), id);
        self.counts.push(0);
        self.matches.push(None);
        id
    }

    fn parts(&self, mut id: u32) -> Vec<&str> {
        let mut parts = Vec::new();
        while id != NO_PARENT {
            let (parent, name, _) = self.nodes[id as usize];
            parts.push(self.names[name as usize].as_str());
            id = parent;
        }
        parts.reverse();
        parts
    }

    fn tables_for(&mut self, id: u32, tables: &[Table]) -> Vec<usize> {
        if let Some(found) = &self.matches[id as usize] {
            return found.clone();
        }
        let parts = self.parts(id);
        let found: Vec<usize> = tables
            .iter()
            .enumerate()
            .filter(|(_, t)| t.patterns.iter().any(|p| p.matches(&parts)))
            .map(|(i, _)| i)
            .collect();
        self.matches[id as usize] = Some(found.clone());
        found
    }
}

struct Frame {
    name: u32,
    path: u32,
    /// (child name, how many seen so far), for sibling positions.
    children: Vec<(u32, u32)>,
    /// (open row, column) waiting for this element's text.
    captures: Vec<(usize, usize)>,
    text: String,
    opened: usize,
}

struct Open {
    table: usize,
    id: i64,
    path: u32,
    depth: usize,
    values: Vec<Option<String>>,
}

fn compile(schema: &Schema) -> Result<Vec<Table>, String> {
    let position = |name: &str| schema.tables.iter().position(|t| t.name == name);
    let mut tables = Vec::new();
    for spec in &schema.tables {
        let patterns = spec.patterns.iter().map(|p| Pattern::parse(p)).collect::<Result<Vec<_>, _>>()?;
        let mut columns = Vec::new();
        let mut by_path: HashMap<String, Vec<usize>> = HashMap::new();
        let mut deepest = 0;
        for (i, c) in spec.columns.iter().enumerate() {
            let kind = match c.kind.as_deref() {
                Some("int") => Kind::Int,
                Some("real") => Kind::Real,
                Some("bool") => Kind::Bool,
                Some("ivec3") => Kind::IVec3,
                _ => Kind::Text,
            };
            let source = if let Some(parent) = &c.parent {
                Source::Parent(position(parent).expect("validated"))
            } else if c.index {
                Source::Index
            } else {
                let path = c.path.as_deref().unwrap_or("").trim_matches('/').to_string();
                deepest = deepest.max(if path.is_empty() { 0 } else { path.split('/').count() });
                by_path.entry(path).or_default().push(i);
                match &c.attr {
                    Some(attr) => Source::Attr(attr.clone()),
                    None => Source::Text,
                }
            };
            let kind = if matches!(source, Source::Parent(_) | Source::Index) { Kind::Int } else { kind };
            columns.push(Column { name: c.name.clone(), kind, source });
        }
        let require =
            spec.require.iter().map(|r| columns.iter().position(|c| &c.name == r).expect("validated")).collect();
        tables.push(Table {
            name: spec.name.clone(),
            patterns,
            columns,
            require,
            indexes: spec.indexes.clone(),
            by_path,
            deepest,
        });
    }
    Ok(tables)
}

fn sql_type(kind: Kind) -> &'static str {
    match kind {
        Kind::Text => "TEXT",
        Kind::Int | Kind::Bool => "INTEGER",
        Kind::Real => "REAL",
        Kind::IVec3 => unreachable!(),
    }
}

fn create_tables(conn: &Connection, tables: &[Table]) -> rusqlite::Result<()> {
    conn.execute_batch(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
         CREATE TABLE element_path (id INTEGER PRIMARY KEY, parent_id INTEGER, depth INTEGER NOT NULL,
                                    name TEXT NOT NULL, path TEXT NOT NULL, count INTEGER NOT NULL);",
    )?;
    for t in tables {
        let mut columns = vec!["id INTEGER PRIMARY KEY".to_string(), "path_id INTEGER NOT NULL".to_string()];
        for c in &t.columns {
            if c.kind == Kind::IVec3 {
                for axis in ["x", "y", "z"] {
                    columns.push(format!("\"{}_{axis}\" INTEGER", c.name));
                }
            } else {
                columns.push(format!("\"{}\" {}", c.name, sql_type(c.kind)));
            }
        }
        conn.execute_batch(&format!("CREATE TABLE \"{}\" ({});", t.name, columns.join(", ")))?;
    }
    Ok(())
}

fn insert_sql(t: &Table) -> String {
    let width = 2 + t.columns.iter().map(|c| if c.kind == Kind::IVec3 { 3 } else { 1 }).sum::<usize>();
    let marks = (1..=width).map(|i| format!("?{i}")).collect::<Vec<_>>().join(", ");
    format!("INSERT INTO \"{}\" VALUES ({marks})", t.name)
}

fn typed(kind: Kind, text: Option<&str>, out: &mut Vec<Value>) {
    let Some(text) = text else {
        let nulls = if kind == Kind::IVec3 { 3 } else { 1 };
        out.extend(std::iter::repeat_n(Value::Null, nulls));
        return;
    };
    let as_text = || Value::Text(text.to_string());
    match kind {
        Kind::Text => out.push(as_text()),
        Kind::Int => out.push(text.parse::<i64>().map(Value::Integer).unwrap_or_else(|_| as_text())),
        Kind::Real => out.push(text.parse::<f64>().map(Value::Real).unwrap_or_else(|_| as_text())),
        Kind::Bool => out.push(match text {
            "True" | "true" => Value::Integer(1),
            "False" | "false" => Value::Integer(0),
            _ => as_text(),
        }),
        Kind::IVec3 => {
            let parts: Vec<Option<i64>> = text
                .trim()
                .trim_start_matches('(')
                .trim_end_matches(')')
                .split(',')
                .map(|p| p.trim().parse::<i64>().ok())
                .collect();
            if parts.len() == 3 && parts.iter().all(Option::is_some) {
                out.extend(parts.into_iter().map(|p| Value::Integer(p.unwrap())));
            } else {
                out.extend(std::iter::repeat_n(Value::Null, 3));
            }
        }
    }
}

fn attribute(element: &BytesStart, name: &str) -> Option<String> {
    let found = element.try_get_attribute(name).ok().flatten()?;
    let value = found
        .unescape_value()
        .map(|v| v.into_owned())
        .unwrap_or_else(|_| String::from_utf8_lossy(&found.value).into_owned());
    if value.is_empty() { None } else { Some(value) }
}

/// Reads the whole of `input` and writes the schema's tables, the path census, `meta` and the views into `conn`,
/// which should be an empty database.
pub fn build<R: BufRead>(
    schema: &Schema,
    input: R,
    conn: &mut Connection,
    meta: &[(String, String)],
) -> Result<Summary, String> {
    let tables = compile(schema)?;
    let db = |e: rusqlite::Error| format!("database: {e}");
    create_tables(conn, &tables).map_err(db)?;
    let tx = conn.transaction().map_err(db)?;
    let mut paths = Paths::default();
    let mut rows = vec![0u64; tables.len()];
    let mut elements = 0u64;
    {
        let mut statements =
            tables.iter().map(|t| tx.prepare(&insert_sql(t))).collect::<Result<Vec<_>, _>>().map_err(db)?;
        let mut reader = Reader::from_reader(input);
        let mut buffer = Vec::with_capacity(64 * 1024);
        let mut stack: Vec<Frame> = Vec::new();
        let mut opens: Vec<Open> = Vec::new();
        let mut key = String::new();
        let mut values: Vec<Value> = Vec::new();

        loop {
            let event = reader
                .read_event_into(&mut buffer)
                .map_err(|e| format!("the XML is not well formed near byte {}: {e}", reader.buffer_position()))?;
            let (start, end) = match &event {
                Event::Start(e) => (Some(e.clone()), false),
                Event::Empty(e) => (Some(e.clone()), true),
                Event::End(_) => (None, true),
                Event::Text(t) => {
                    if let Some(top) = stack.last_mut() {
                        if !top.captures.is_empty() {
                            match t.unescape() {
                                Ok(text) => top.text.push_str(&text),
                                Err(_) => top.text.push_str(&String::from_utf8_lossy(t)),
                            }
                        }
                    }
                    (None, false)
                }
                Event::CData(c) => {
                    if let Some(top) = stack.last_mut() {
                        if !top.captures.is_empty() {
                            top.text.push_str(&String::from_utf8_lossy(c));
                        }
                    }
                    (None, false)
                }
                Event::Eof => break,
                _ => (None, false),
            };

            if let Some(element) = start {
                elements += 1;
                let id = elements as i64;
                let name = paths.name(element.name().as_ref());
                let parent_path = stack.last().map_or(NO_PARENT, |f| f.path);
                let path = paths.node(parent_path, name);
                paths.counts[path as usize] += 1;
                let depth = stack.len() + 1;
                let sibling = match stack.last_mut() {
                    Some(top) => match top.children.iter_mut().find(|(n, _)| *n == name) {
                        Some((_, seen)) => {
                            *seen += 1;
                            *seen - 1
                        }
                        None => {
                            top.children.push((name, 1));
                            0
                        }
                    },
                    None => 0,
                };

                let mut captures = Vec::new();
                for (oi, open) in opens.iter_mut().enumerate() {
                    let table = &tables[open.table];
                    let relative = depth - open.depth;
                    if relative == 0 || relative > table.deepest {
                        continue;
                    }
                    key.clear();
                    for frame in &stack[open.depth..] {
                        key.push_str(&paths.names[frame.name as usize]);
                        key.push('/');
                    }
                    key.push_str(&paths.names[name as usize]);
                    if let Some(columns) = table.by_path.get(key.as_str()) {
                        for &c in columns {
                            match &table.columns[c].source {
                                Source::Text => captures.push((oi, c)),
                                Source::Attr(attr) if open.values[c].is_none() => {
                                    open.values[c] = attribute(&element, attr);
                                }
                                _ => {}
                            }
                        }
                    }
                }

                let mut opened = 0;
                for t in paths.tables_for(path, &tables) {
                    let table = &tables[t];
                    let mut row = vec![None; table.columns.len()];
                    for (c, column) in table.columns.iter().enumerate() {
                        row[c] = match &column.source {
                            Source::Index => Some(sibling.to_string()),
                            Source::Parent(p) => opens.iter().rev().find(|o| o.table == *p).map(|o| o.id.to_string()),
                            _ => None,
                        };
                    }
                    if let Some(columns) = table.by_path.get("") {
                        for &c in columns {
                            match &table.columns[c].source {
                                Source::Text => captures.push((opens.len(), c)),
                                Source::Attr(attr) => row[c] = attribute(&element, attr),
                                _ => {}
                            }
                        }
                    }
                    opens.push(Open { table: t, id, path, depth, values: row });
                    opened += 1;
                }
                stack.push(Frame { name, path, children: Vec::new(), captures, text: String::new(), opened });
            }

            if end {
                let frame = stack.pop().ok_or("the XML closes an element it never opened")?;
                let text = frame.text.trim();
                if !text.is_empty() {
                    for (oi, c) in frame.captures {
                        if opens[oi].values[c].is_none() {
                            opens[oi].values[c] = Some(text.to_string());
                        }
                    }
                }
                for _ in 0..frame.opened {
                    let open = opens.pop().expect("opened at this frame");
                    let table = &tables[open.table];
                    if table.require.iter().any(|&c| open.values[c].is_none()) {
                        continue;
                    }
                    values.clear();
                    values.push(Value::Integer(open.id));
                    values.push(Value::Integer(open.path as i64));
                    for (c, column) in table.columns.iter().enumerate() {
                        typed(column.kind, open.values[c].as_deref(), &mut values);
                    }
                    statements[open.table].execute(params_from_iter(values.iter())).map_err(db)?;
                    rows[open.table] += 1;
                }
            }
            buffer.clear();
        }
        if !stack.is_empty() {
            return Err(format!("the file ends inside <{}>: it is cut short", paths.names[stack[0].name as usize]));
        }
        if elements == 0 {
            return Err("the file holds no XML elements".to_string());
        }

        let mut insert = tx.prepare("INSERT INTO element_path VALUES (?1, ?2, ?3, ?4, ?5, ?6)").map_err(db)?;
        let mut full: Vec<String> = Vec::with_capacity(paths.nodes.len());
        for (id, &(parent, name, depth)) in paths.nodes.iter().enumerate() {
            let name = &paths.names[name as usize];
            let path = if parent == NO_PARENT { name.clone() } else { format!("{}/{name}", full[parent as usize]) };
            let parent = if parent == NO_PARENT { Value::Null } else { Value::Integer(parent as i64) };
            insert
                .execute(rusqlite::params![id as i64, parent, depth, name, path, paths.counts[id] as i64])
                .map_err(db)?;
            full.push(path);
        }
        let mut insert = tx.prepare("INSERT INTO meta VALUES (?1, ?2)").map_err(db)?;
        let built_in = [
            ("indexer".to_string(), "xml-index".to_string()),
            ("indexer_version".to_string(), env!("CARGO_PKG_VERSION").to_string()),
            ("schema".to_string(), schema.name.clone()),
            ("schema_format".to_string(), schema.format.to_string()),
            ("elements".to_string(), elements.to_string()),
        ];
        for (k, v) in built_in.iter().chain(meta) {
            insert.execute(rusqlite::params![k, v]).map_err(|e| format!("meta key \"{k}\": {e}"))?;
        }
    }
    for t in &tables {
        for column in &t.indexes {
            tx.execute_batch(&format!("CREATE INDEX \"{0}__{1}\" ON \"{0}\" (\"{1}\");", t.name, column))
                .map_err(db)?;
        }
    }
    for view in &schema.views {
        tx.execute_batch(&format!("CREATE VIEW \"{}\" AS {};", view.name, view.sql))
            .map_err(|e| format!("view \"{}\": {e}", view.name))?;
    }
    tx.commit().map_err(db)?;
    Ok(Summary {
        elements,
        paths: paths.nodes.len(),
        rows: tables.iter().zip(rows).map(|(t, n)| (t.name.clone(), n)).collect(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const SCHEMA: &str = r#"
        format = 1
        name = "test"

        [[table]]
        name = "doc"
        match = ["root"]
        [[table.column]]
        name = "version"
        path = "meta/version"
        [[table.column]]
        name = "ticks"
        path = "meta/ticks"
        type = "int"

        [[table]]
        name = "thing"
        match = ["root/things/thing", "**/innerList/li"]
        require = ["def"]
        indexes = ["def"]
        [[table.column]]
        name = "def"
        path = "def"
        [[table.column]]
        name = "class"
        attr = "Class"
        [[table.column]]
        name = "pos"
        path = "pos"
        type = "ivec3"
        [[table.column]]
        name = "stack"
        path = "stackCount"
        type = "int"
        [[table.column]]
        name = "forbidden"
        path = "forbidden"
        type = "bool"
        [[table.column]]
        name = "holder"
        parent = "thing"
        [[table.column]]
        name = "first_name"
        path = "name/first"
        [[table.column]]
        name = "name_class"
        path = "name"
        attr = "Class"

        [[table]]
        name = "mod"
        match = ["root/mods/li"]
        [[table.column]]
        name = "position"
        index = true
        [[table.column]]
        name = "package_id"
        path = ""

        [[view]]
        name = "held"
        sql = "SELECT * FROM thing WHERE holder IS NOT NULL"
    "#;

    const XML: &str = r#"<?xml version="1.0" encoding="utf-8"?>
<root>
  <meta><version>1.7 &amp; more</version><ticks>12345</ticks></meta>
  <mods><li>core</li><li>example.one</li><li><![CDATA[example.<two>]]></li></mods>
  <things>
    <thing Class="Pawn">
      <def>Human</def>
      <pos>(10, 0, 20)</pos>
      <name Class="NameTriple"><first>Ann</first></name>
      <inventory><innerContainer><innerList>
        <li Class="ThingWithComps"><def>MealSimple</def><stackCount>3</stackCount><forbidden>True</forbidden></li>
      </innerList></innerContainer></inventory>
    </thing>
    <thing Class="Building"><def>Wall</def><pos>(1, 0, 2)</pos><def>Ignored</def></thing>
    <thing>Thing_Reference123</thing>
    <thing Class="Filth"><def>Filth_Dirt</def><pos>not a vector</pos><stackCount>many</stackCount><questTags /></thing>
  </things>
</root>"#;

    fn build_test(xml: &str) -> (Connection, Result<Summary, String>) {
        let schema = Schema::parse(SCHEMA).unwrap();
        let mut conn = Connection::open_in_memory().unwrap();
        let meta = vec![("source".to_string(), "test.xml".to_string())];
        let result = build(&schema, xml.as_bytes(), &mut conn, &meta);
        (conn, result)
    }

    fn rows(conn: &Connection, sql: &str) -> Vec<Vec<Value>> {
        let mut statement = conn.prepare(sql).unwrap();
        let width = statement.column_count();
        statement
            .query_map([], |r| (0..width).map(|i| r.get::<_, Value>(i)).collect())
            .unwrap()
            .map(Result::unwrap)
            .collect()
    }

    fn text(v: &str) -> Value {
        Value::Text(v.to_string())
    }

    #[test]
    fn rows_have_their_columns_typed() {
        let (conn, result) = build_test(XML);
        let summary = result.unwrap();
        assert_eq!(summary.rows, vec![("doc".into(), 1), ("thing".into(), 4), ("mod".into(), 3)]);
        let things = rows(&conn, "SELECT def, class, pos_x, pos_z, stack, forbidden FROM thing ORDER BY id");
        assert_eq!(
            things[0],
            vec![text("Human"), text("Pawn"), Value::Integer(10), Value::Integer(20), Value::Null, Value::Null]
        );
        assert_eq!(
            things[1],
            vec![
                text("MealSimple"),
                text("ThingWithComps"),
                Value::Null,
                Value::Null,
                Value::Integer(3),
                Value::Integer(1)
            ]
        );
        assert_eq!(things[2][0], text("Wall"), "the first value of a repeated element wins");
        assert_eq!(things[3][2], Value::Null, "an unreadable vector is null");
        assert_eq!(things[3][4], text("many"), "an unreadable number is kept as text");
    }

    #[test]
    fn elements_without_required_values_are_not_rows() {
        let (conn, _) = build_test(XML);
        assert!(rows(&conn, "SELECT def FROM thing").iter().all(|r| r[0] != Value::Null));
    }

    #[test]
    fn nested_rows_point_at_their_parent() {
        let (conn, _) = build_test(XML);
        let held = rows(&conn, "SELECT h.def, p.def FROM held h JOIN thing p ON p.id = h.holder");
        assert_eq!(held, vec![vec![text("MealSimple"), text("Human")]]);
    }

    #[test]
    fn deeper_paths_attributes_entities_and_cdata() {
        let (conn, _) = build_test(XML);
        let pawn = rows(&conn, "SELECT first_name, name_class FROM thing WHERE def = 'Human'");
        assert_eq!(pawn, vec![vec![text("Ann"), text("NameTriple")]]);
        assert_eq!(
            rows(&conn, "SELECT version, ticks FROM doc"),
            vec![vec![text("1.7 & more"), Value::Integer(12345)]]
        );
        let mods = rows(&conn, "SELECT position, package_id FROM mod ORDER BY position");
        assert_eq!(mods[2], vec![Value::Integer(2), text("example.<two>")]);
    }

    #[test]
    fn the_census_counts_every_path() {
        let (conn, result) = build_test(XML);
        let counted = rows(&conn, "SELECT count FROM element_path WHERE path = 'root/things/thing'");
        assert_eq!(counted, vec![vec![Value::Integer(4)]]);
        let summary = result.unwrap();
        let total = rows(&conn, "SELECT SUM(count) FROM element_path");
        assert_eq!(total, vec![vec![Value::Integer(summary.elements as i64)]]);
        assert_eq!(rows(&conn, "SELECT value FROM meta WHERE key = 'source'"), vec![vec![text("test.xml")]]);
    }

    #[test]
    fn ids_follow_document_order() {
        let (conn, _) = build_test(XML);
        let ids: Vec<i64> = rows(&conn, "SELECT id FROM thing ORDER BY id")
            .into_iter()
            .map(|r| match r[0] {
                Value::Integer(i) => i,
                _ => panic!(),
            })
            .collect();
        let defs = rows(&conn, "SELECT def FROM thing ORDER BY id");
        assert_eq!(
            defs.iter().map(|r| r[0].clone()).collect::<Vec<_>>(),
            vec![text("Human"), text("MealSimple"), text("Wall"), text("Filth_Dirt")]
        );
        assert!(ids.windows(2).all(|w| w[0] < w[1]));
    }

    #[test]
    fn a_file_cut_short_is_an_error() {
        let (_, result) = build_test(&XML[..XML.len() - 20]);
        assert!(result.unwrap_err().contains("cut short"));
    }

    #[test]
    fn broken_xml_is_an_error() {
        let (_, result) = build_test("<root><a></b></root>");
        assert!(result.unwrap_err().contains("not well formed"));
    }
}
