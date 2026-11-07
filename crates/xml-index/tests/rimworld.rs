//! The RimWorld adapter's schema, run over the hand-written fixture save: the schema must load, and every table
//! and view must hold what the fixture says.

use rusqlite::Connection;
use std::fs::File;
use std::io::BufReader;
use std::path::PathBuf;
use xml_index::{Schema, build};

fn kit_file(relative: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..").join(relative)
}

fn indexed() -> Connection {
    let text = std::fs::read_to_string(kit_file("python/phobos_modkit/games/rimworld/save-schema.toml")).unwrap();
    let schema = Schema::parse(&text).expect("the RimWorld schema is valid");
    let save = File::open(kit_file("fixtures/rimworld/Example.rws")).unwrap();
    let mut conn = Connection::open_in_memory().unwrap();
    build(&schema, BufReader::new(save), &mut conn, &[]).expect("the fixture indexes");
    conn
}

fn count(conn: &Connection, sql: &str) -> i64 {
    conn.query_row(sql, [], |r| r.get(0)).unwrap()
}

#[test]
fn every_table_holds_what_the_fixture_has() {
    let conn = indexed();
    for (table, expected) in [
        ("game", 1),
        ("mod_id", 3),
        ("faction", 2),
        ("map", 1),
        ("thing", 10),
        ("pawn", 4),
        ("hediff", 3),
        ("trait", 2),
        ("skill", 1),
    ] {
        assert_eq!(count(&conn, &format!("SELECT COUNT(*) FROM {table}")), expected, "{table}");
    }
}

#[test]
fn bare_references_to_things_are_not_things() {
    let conn = indexed();
    assert_eq!(count(&conn, "SELECT COUNT(*) FROM thing WHERE thing_id = 'Steel101'"), 1);
}

#[test]
fn places_follow_holders_to_the_outermost_thing() {
    let conn = indexed();
    let (place, held, top): (String, i64, String) = conn
        .query_row(
            "SELECT pl.place, pl.held, top.thing_id FROM thing t JOIN thing_place pl ON pl.id = t.id
             JOIN thing top ON top.id = pl.top_id WHERE t.thing_id = 'MealSimple102'",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap();
    assert_eq!((place.as_str(), held, top.as_str()), ("map", 1, "Human200"));
    assert_eq!(count(&conn, "SELECT COUNT(*) FROM thing_place WHERE place = 'world pawn'"), 1);
    assert_eq!(count(&conn, "SELECT COUNT(*) FROM thing_place WHERE place = 'dead world pawn'"), 1);
}

#[test]
fn pawn_names_factions_and_ages() {
    let conn = indexed();
    let mut statement =
        conn.prepare("SELECT name, faction_name, place, age_years FROM pawn_view ORDER BY name").unwrap();
    let pawns: Vec<(String, String, String, Option<i64>)> = statement
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    assert_eq!(
        pawns,
        vec![
            ("Annie".into(), "Example Colony".into(), "map".into(), Some(30)),
            ("Cora Example".into(), "Example Raiders".into(), "world pawn".into(), Some(40)),
            ("Dov".into(), "Example Raiders".into(), "dead world pawn".into(), None),
            ("Eli Example".into(), "Example Raiders".into(), "map".into(), None),
        ]
    );
}

#[test]
fn hediffs_belong_to_their_pawn() {
    let conn = indexed();
    assert_eq!(
        count(
            &conn,
            "SELECT COUNT(*) FROM hediff h JOIN pawn_view p ON p.id = h.pawn
             WHERE p.name = 'Annie' AND h.def = 'Gunshot' AND h.part_index = 12 AND h.severity = 4.5"
        ),
        1
    );
}

#[test]
fn mods_line_up_across_the_three_lists() {
    let conn = indexed();
    let (id, name, steam): (String, String, String) = conn
        .query_row("SELECT package_id, name, steam_id FROM mods WHERE position = 2", [], |r| {
            Ok((r.get(0)?, r.get(1)?, r.get(2)?))
        })
        .unwrap();
    assert_eq!((id.as_str(), name.as_str(), steam.as_str()), ("example.widgets", "Example Widgets", "2222222222"));
}
