"""A RimWorld mod's XML read without the game: lines, files, load folders by version, inheritance, and patches applied.

Every mod here is made up in a temporary folder; nothing reads an install.
"""
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

import support  # noqa: F401  (puts the package on the import path)
from phobos_modkit.games.rimworld.loading import load_folders_by_version, version_key
from phobos_modkit.games.rimworld.mod_xml import FROM, ModXml, line_of, merge, package_id, parse_lines, resolve_defs, text
from phobos_modkit.games.rimworld.xml_patches import Patcher, xpath_targets


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class Folder(unittest.TestCase):
    def setUp(self):
        self.mod = Path(tempfile.mkdtemp()) / "MyMod"
        self.mod.mkdir()

    def tearDown(self):
        shutil.rmtree(self.mod.parent, ignore_errors=True)


class LoadFolders(Folder):
    def test_every_block_of_load_folders_whatever_it_waits_for(self):
        write(self.mod / "LoadFolders.xml", "<loadFolders><v1.6><li>/</li><li>1.6</li></v1.6>"
                                            "<v1.7><li></li><li IfModActive='other.mod'>Mods\\Other</li></v1.7></loadFolders>")
        self.assertEqual(load_folders_by_version(self.mod),
                         {"1.6": [self.mod, self.mod / "1.6"], "1.7": [self.mod, self.mod / "Mods\\Other"]})

    def test_without_load_folders_each_version_folder_with_root_and_common(self):
        for name in ("Common", "1.10", "1.7", "Textures"):
            (self.mod / name).mkdir()
        self.assertEqual(load_folders_by_version(self.mod), {
            "1.7": [self.mod, self.mod / "Common", self.mod / "1.7"],
            "1.10": [self.mod, self.mod / "Common", self.mod / "1.10"]})

    def test_no_versions_at_all_and_a_broken_listing(self):
        write(self.mod / "LoadFolders.xml", "<loadFolders><v1.7>")
        self.assertEqual(load_folders_by_version(self.mod), {"": [self.mod]})
        self.assertEqual(version_key(""), ())
        self.assertLess(version_key("1.9"), version_key("1.10"))


class Reading(Folder):
    def test_defs_patches_keys_lines_and_broken_files(self):
        write(self.mod / "About/About.xml", "<ModMetaData><packageId> My.Mod </packageId></ModMetaData>")
        write(self.mod / "Defs/A.xml", "<Defs>\n  <ThingDef>\n    <defName>A</defName>\n  </ThingDef>\n  <!-- a note -->\n</Defs>")
        write(self.mod / "Patches/P.xml", "<Patch><Operation Class='PatchOperationAdd'/></Patch>")
        write(self.mod / "Languages/English/Keyed/K.xml", "<LanguageData><Key_One>One</Key_One></LanguageData>")
        write(self.mod / "Defs/Broken.xml", "<Defs>\n<ThingDef>\n</Defs>")
        files = ModXml(self.mod, "MyMod", [self.mod])
        self.assertEqual(package_id(self.mod), "My.Mod")
        self.assertEqual([(node.tag, source, line_of(node)) for node, source in files.defs], [("ThingDef", "MyMod/Defs/A.xml", 2)])
        self.assertEqual(line_of(files.defs[0][0].find("defName")), 3)
        self.assertEqual([source for _, source in files.patches], ["MyMod/Patches/P.xml"])
        self.assertEqual(files.keys, {"Key_One"})
        self.assertEqual(len(files.broken), 1)
        self.assertEqual(files.broken[0][:2], ("MyMod/Defs/Broken.xml", 3))
        self.assertIn("not well-formed XML", files.broken[0][2])
        self.assertEqual(package_id(self.mod / "Nowhere"), "")

    def test_a_file_is_read_once_even_when_two_load_folders_reach_it(self):
        write(self.mod / "Defs/A.xml", "<Defs><ThingDef><defName>A</defName></ThingDef></Defs>")
        self.assertEqual(len(ModXml(self.mod, "MyMod", [self.mod, self.mod]).defs), 1)


def element(xml):
    return ET.fromstring(xml)


class Inheritance(unittest.TestCase):
    def test_lists_append_leaves_override_and_inherit_false_replaces(self):
        parent = element("<D Name='P' Abstract='True'><a>1</a><list><li>x</li></list><keep><li>k</li></keep>"
                         "<deep><b>1</b><c>2</c></deep></D>")
        child = element("<D ParentName='P'><defName>C</defName><a>2</a><list><li>y</li></list>"
                        "<keep Inherit='False'><li>only</li></keep><deep><c>3</c></deep></D>")
        merged = merge(parent, child)
        self.assertNotIn("Abstract", merged.attrib)
        self.assertEqual(merged.attrib["Name"], "P", "the parent's Name stays; the child's is not taken")
        self.assertEqual(text(merged, "a"), "2")
        self.assertEqual([li.text for li in merged.find("list")], ["x", "y"])
        self.assertEqual([li.text for li in merged.find("keep")], ["only"])
        self.assertEqual((text(merged, "deep/b"), text(merged, "deep/c")), ("1", "3"))
        self.assertEqual(text(merged, "defName"), "C")

    def test_a_parent_is_looked_for_in_the_childs_own_mod_first(self):
        theirs_base = element("<D Name='Base' Abstract='True'><from>theirs</from></D>")
        ours_base = element("<D Name='Base' Abstract='True'><from>ours</from></D>")
        child = element("<D ParentName='Base'><defName>C</defName></D>")
        orphan = element("<D ParentName='Nowhere'><defName>O</defName></D>")
        other_type = element("<E ParentName='Base'><defName>X</defName></E>")
        nodes = [(ours_base, "ours.xml"), (theirs_base, "theirs.xml"), (child, "theirs.xml"), (orphan, "theirs.xml"),
                 (other_type, "theirs.xml")]
        owner_of = {id(ours_base): "ours", id(theirs_base): "theirs", id(child): "theirs", id(orphan): "theirs",
                    id(other_type): "theirs"}
        resolved, missing, original_of = resolve_defs(nodes, owner_of, ("F", "D"))
        self.assertEqual(list(resolved), ["F", "D", "E"], "a key for each tag asked for first, in that order")
        self.assertEqual([text(node, "from") for node, _ in resolved["D"]], ["theirs", None])
        self.assertEqual(missing, [orphan, other_type], "a parent of another Def type is no parent")
        first = resolved["D"][0][0]
        self.assertIs(original_of[id(first)], child)
        self.assertEqual(owner_of[id(first)], "theirs")


class Patching(unittest.TestCase):
    def setUp(self):
        self.document = element("<Defs><ThingDef><defName>A</defName><list><li>1</li></list></ThingDef>"
                                "<ThingDef><defName>B</defName></ThingDef></Defs>")

    def apply(self, operations, mentions=None):
        patcher = Patcher(self.document, mentions)
        patcher.apply(element(f"<Patch>{operations}</Patch>"), "MyMod/Patches/P.xml")
        return patcher

    def a(self):
        return self.document[0]

    def test_add_insert_replace_remove_and_attributes(self):
        patcher = self.apply(
            "<Operation Class='PatchOperationAdd'><xpath>Defs/ThingDef[defName=\"A\"]/list</xpath><value><li>2</li></value></Operation>"
            "<Operation Class='PatchOperationAdd'><xpath>Defs/ThingDef[defName=\"A\"]/list</xpath><order>Prepend</order>"
            "<value><li>0</li></value></Operation>"
            "<Operation Class='PatchOperationInsert'><xpath>Defs/ThingDef[defName=\"A\"]/defName</xpath><order>Append</order>"
            "<value><label>a</label></value></Operation>"
            "<Operation Class='PatchOperationReplace'><xpath>//ThingDef[defName=\"B\"]/defName</xpath>"
            "<value><defName>B2</defName></value></Operation>"
            "<Operation Class='PatchOperationAttributeSet'><xpath>Defs/ThingDef[defName=\"A\"]</xpath><attribute>Name</attribute>"
            "<value>Named</value></Operation>"
            "<Operation Class='PatchOperationRemove'><xpath>Defs/ThingDef[defName=\"A\"]/list/li[1]</xpath></Operation>")
        self.assertEqual(patcher.findings, [])
        self.assertEqual([child.tag for child in self.a()], ["defName", "label", "list"])
        self.assertEqual([li.text for li in self.a().find("list")], ["1", "2"])
        self.assertEqual(self.a().attrib["Name"], "Named")
        self.assertEqual(text(self.document[1], "defName"), "B2")
        self.assertEqual(self.a().find("label").attrib[FROM], "MyMod/Patches/P.xml")
        self.assertEqual(set(patcher.touched), {id(self.a()), id(self.document[1])})

    def test_sequences_conditionals_and_find_mod(self):
        self.apply("<Operation Class='PatchOperationSequence'><operations>"
                   "<li Class='PatchOperationConditional'><xpath>Defs/ThingDef[defName=\"A\"]/label</xpath>"
                   "<nomatch Class='PatchOperationAdd'><xpath>Defs/ThingDef[defName=\"A\"]</xpath><value><label>new</label></value>"
                   "</nomatch></li>"
                   "<li Class='PatchOperationFindMod'><mods><li>Other</li></mods><match Class='PatchOperationAdd'>"
                   "<xpath>Defs/ThingDef[defName=\"B\"]</xpath><value><label>b</label></value></match></li>"
                   "</operations></Operation>")
        self.assertEqual((text(self.a(), "label"), text(self.document[1], "label")), ("new", "b"))

    def test_what_cannot_be_followed_is_a_note_and_a_patch_finding_nothing_an_error(self):
        patcher = self.apply(
            "<Operation Class='PatchOperationAdd'><xpath>Defs/ThingDef[defName=\"Z\"]</xpath><value><a/></value></Operation>"
            "<Operation Class='PatchOperationAdd'><xpath>Defs/ThingDef[defName=\"Z\"]</xpath><success>Always</success>"
            "<value><a/></value></Operation>"
            "<Operation Class='PatchOperationAdd'><xpath>Defs/ThingDef[contains(defName, \"A\")]</xpath><value><a/></value></Operation>"
            "<Operation Class='OtherMod.PatchOperationSpecial'><xpath>Defs/ThingDef</xpath></Operation>"
            "<Operation Class='PatchOperationAdd'><xpath>Defs/ThingDef[defName=\"Elsewhere\"]</xpath><value><a/></value></Operation>",
            mentions=lambda xpath: "Elsewhere" not in xpath)
        self.assertEqual([(severity, problem.split(":")[0]) for severity, _, _, problem in patcher.findings], [
            ("error", 'the patch on Defs/ThingDef[defName="Z"] changes nothing'),
            ("note", 'the patch on Defs/ThingDef[contains(defName, "A")] was not followed'),
            ("note", "a PatchOperationSpecial on Defs/ThingDef was not followed")])

    def test_xpaths_this_can_follow(self):
        self.assertEqual(xpath_targets(self.document, "/Defs"), [self.document])
        self.assertEqual(len(xpath_targets(self.document, "Defs/ThingDef")), 2)
        self.assertEqual(len(xpath_targets(self.document, "//li")), 1)
        for beyond in ("Defs/ThingDef | Defs/Other", "Defs/ThingDef[last()]", "Other/ThingDef", "", None):
            self.assertIsNone(xpath_targets(self.document, beyond), beyond)


class Lines(unittest.TestCase):
    def test_parse_lines_keeps_each_elements_first_line(self):
        folder = Path(tempfile.mkdtemp())
        try:
            write(folder / "a.xml", "<?xml version='1.0'?>\n<Defs>\n\n  <A\n    x='1'>\n    <b/></A>\n</Defs>")
            root = parse_lines(folder / "a.xml")
            self.assertEqual((line_of(root), line_of(root[0]), line_of(root[0][0])), (2, 4, 6))
            self.assertIsNone(line_of(element("<a/>")))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
