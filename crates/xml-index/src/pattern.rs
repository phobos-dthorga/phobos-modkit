//! Element-path patterns: "root/things/thing", "**/innerList/li", "root/*/li".
//!
//! A pattern matches a whole path from the root element. `*` matches one part, `**` any number of parts
//! (including none).

#[derive(Debug, Clone, PartialEq, Eq)]
enum Part {
    Name(String),
    One,
    Any,
}

#[derive(Debug, Clone)]
pub struct Pattern {
    parts: Vec<Part>,
}

impl Pattern {
    pub fn parse(text: &str) -> Result<Pattern, String> {
        let text = text.trim().trim_matches('/');
        if text.is_empty() {
            return Err("an empty pattern matches nothing".to_string());
        }
        let parts = text
            .split('/')
            .map(|part| match part {
                "**" => Ok(Part::Any),
                "*" => Ok(Part::One),
                "" => Err(format!("pattern \"{text}\" has an empty part")),
                name if name.contains('*') => Err(format!("pattern \"{text}\": * stands alone in a part")),
                name => Ok(Part::Name(name.to_string())),
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Pattern { parts })
    }

    pub fn matches<S: AsRef<str>>(&self, path: &[S]) -> bool {
        fn go<S: AsRef<str>>(parts: &[Part], path: &[S]) -> bool {
            match parts.split_first() {
                None => path.is_empty(),
                Some((Part::Any, rest)) => (0..=path.len()).any(|skip| go(rest, &path[skip..])),
                Some((part, rest)) => match path.split_first() {
                    None => false,
                    Some((head, tail)) => {
                        let fits = match part {
                            Part::One => true,
                            Part::Name(name) => name == head.as_ref(),
                            Part::Any => unreachable!(),
                        };
                        fits && go(rest, tail)
                    }
                },
            }
        }
        go(&self.parts, path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn m(pattern: &str, path: &str) -> bool {
        Pattern::parse(pattern).unwrap().matches(&path.split('/').collect::<Vec<_>>())
    }

    #[test]
    fn exact_paths() {
        assert!(m("root/things/thing", "root/things/thing"));
        assert!(!m("root/things/thing", "root/things/thing/def"));
        assert!(!m("root/things/thing", "root/things"));
    }

    #[test]
    fn one_part_wildcard() {
        assert!(m("root/*/li", "root/pawnsDead/li"));
        assert!(!m("root/*/li", "root/a/b/li"));
    }

    #[test]
    fn any_parts_wildcard() {
        assert!(m("**/innerList/li", "root/x/innerList/li"));
        assert!(m("**/innerList/li", "innerList/li"));
        assert!(m("root/**/li", "root/li"));
        assert!(m("a/**/b/**/c", "a/x/b/y/z/c"));
        assert!(!m("**/innerList/li", "root/innerList/li/def"));
    }

    #[test]
    fn bad_patterns_are_refused() {
        assert!(Pattern::parse("").is_err());
        assert!(Pattern::parse("a//b").is_err());
        assert!(Pattern::parse("a/b*").is_err());
    }
}
