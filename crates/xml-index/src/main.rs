//! xml-index build --schema SCHEMA --out INDEX [--meta KEY=VALUE]... [--force] INPUT
//!
//! Reads INPUT once and writes the SQLite index to INDEX, through a temporary file renamed into place at the end,
//! so a failed build never leaves a half-written index. Prints one line of JSON: elements, paths, rows per table
//! and seconds. Reads INPUT only; never writes beside it.

use rusqlite::Connection;
use std::fs::{self, File};
use std::io::BufReader;
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Instant;
use xml_index::{Schema, build};

const USAGE: &str = "usage: xml-index build --schema SCHEMA --out INDEX [--meta KEY=VALUE]... [--force] INPUT
       xml-index --version";
const READ_BUFFER: usize = 1 << 20;

struct Options {
    schema: PathBuf,
    out: PathBuf,
    input: PathBuf,
    meta: Vec<(String, String)>,
    force: bool,
}

fn parse(args: &[String]) -> Result<Options, String> {
    let mut schema = None;
    let mut out = None;
    let mut input = None;
    let mut meta = Vec::new();
    let mut force = false;
    let mut items = args.iter();
    while let Some(arg) = items.next() {
        let mut value = |flag: &str| items.next().cloned().ok_or(format!("{flag} needs a value"));
        match arg.as_str() {
            "--schema" => schema = Some(PathBuf::from(value("--schema")?)),
            "--out" => out = Some(PathBuf::from(value("--out")?)),
            "--meta" => {
                let pair = value("--meta")?;
                let (k, v) = pair.split_once('=').ok_or(format!("--meta {pair}: write it as KEY=VALUE"))?;
                meta.push((k.to_string(), v.to_string()));
            }
            "--force" => force = true,
            flag if flag.starts_with("--") => return Err(format!("unknown option {flag}")),
            path if input.is_none() => input = Some(PathBuf::from(path)),
            extra => return Err(format!("one input file only (also got {extra})")),
        }
    }
    Ok(Options {
        schema: schema.ok_or("--schema is required")?,
        out: out.ok_or("--out is required")?,
        input: input.ok_or("name the XML file to read")?,
        meta,
        force,
    })
}

fn run(options: Options) -> Result<String, String> {
    let schema_text = fs::read_to_string(&options.schema)
        .map_err(|e| format!("cannot read the schema {}: {e}", options.schema.display()))?;
    let schema = Schema::parse(&schema_text)?;
    if options.out.exists() && !options.force {
        return Err(format!("{} already exists; add --force to replace it", options.out.display()));
    }
    let file = File::open(&options.input).map_err(|e| format!("cannot read {}: {e}", options.input.display()))?;
    let partial = options.out.with_extension("partial");
    let _ = fs::remove_file(&partial);
    let started = Instant::now();
    let summary = {
        let mut conn = Connection::open(&partial).map_err(|e| format!("cannot create {}: {e}", partial.display()))?;
        conn.execute_batch("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF; PRAGMA temp_store = MEMORY;")
            .map_err(|e| format!("database: {e}"))?;
        match build(&schema, BufReader::with_capacity(READ_BUFFER, file), &mut conn, &options.meta) {
            Ok(summary) => summary,
            Err(e) => {
                drop(conn);
                let _ = fs::remove_file(&partial);
                return Err(e);
            }
        }
    };
    if options.out.exists() {
        fs::remove_file(&options.out).map_err(|e| format!("cannot replace {}: {e}", options.out.display()))?;
    }
    fs::rename(&partial, &options.out).map_err(|e| format!("cannot move the index into place: {e}"))?;
    let rows = summary.rows.iter().map(|(t, n)| format!("\"{t}\":{n}")).collect::<Vec<_>>().join(",");
    Ok(format!(
        "{{\"elements\":{},\"paths\":{},\"rows\":{{{rows}}},\"seconds\":{:.2}}}",
        summary.elements,
        summary.paths,
        started.elapsed().as_secs_f64()
    ))
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("--version") => {
            println!("xml-index {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        Some("build") => match parse(&args[1..]).and_then(run) {
            Ok(line) => {
                println!("{line}");
                ExitCode::SUCCESS
            }
            Err(e) => {
                eprintln!("xml-index: {e}");
                ExitCode::FAILURE
            }
        },
        _ => {
            eprintln!("{USAGE}");
            ExitCode::from(2)
        }
    }
}
