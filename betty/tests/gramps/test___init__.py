from pathlib import Path
from tempfile import TemporaryDirectory

from reactives import ReactiveList

from betty.app import App
from betty.gramps import Gramps, GrampsConfiguration
from betty.gramps.config import FamilyTreeConfiguration
from betty.load import load
from betty.model.ancestry import Citation, Note, Source, File, \
    Event, Person, Place
from betty.project import ExtensionConfiguration


class TestGramps:
    async def test_load_multiple_family_trees(self):
        family_tree_one_xml = """
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.1//EN"
"http://gramps-project.org/xml/1.7.1/grampsxml.dtd">
<database xmlns="http://gramps-project.org/xml/1.7.1/">
  <header>
    <created date="2019-03-09" version="4.2.8"/>
    <researcher>
    </researcher>
  </header>
  <objects>
    <object handle="_e21e77b318dcbf5114e53d2ccf" change="1553878032" id="O0001">
      <file src="/home/bart/Desktop/1px.gif" mime="image/gif" checksum="c4f9b77f41082b633d120e2915c1ea2e" description="1px"/>
    </object>
  </objects>
  <people>
    <person handle="_e1dd3ac2fa22e6fefa18f738bdd" change="1552126811" id="I0001">
    </person>
  </people>
  <places>
    <placeobj handle="_e1dd2fb639e3f04f8cfabaa7e8a" change="1552125653" id="P0001" type="Unknown">
    </placeobj>
  </places>
  <events>
    <event handle="_e1dd3ac2fa22e6fefa18f738bdd" change="1552126811" id="E0001">
      <type>Birth</type>
    </event>
  </events>
  <sources>
    <source handle="_e2b5e77b4cc5c91c9ed60a6cb39" change="1558277217" id="S0001">
      <stitle>A Whisper</stitle>
      <reporef hlink="_e2c257f50fd27b1c841d7497448" medium="Book"/>
    </source>
  </sources>
  <repositories>
    <repository handle="_e2c257f50fd27b1c841d7497448" change="1558277216" id="R0001">
      <rname>Library of Alexandria</rname>
    </repository>
  </repositories>
  <citations>
    <citation handle="_e2c25a12a097a0b24bd9eae5090" change="1558277266" id="C0001">
      <sourceref hlink="_e2b5e77b4cc5c91c9ed60a6cb39"/>
    </citation>
  </citations>
  <notes>
    <note handle="_e1cb35d7e6c1984b0e8361e1aee" change="1551643112" id="N0001" type="Transcript">
      <text></text>
    </note>
  </notes>
</database>
""".strip()
        family_tree_two_xml = """
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.1//EN"
"http://gramps-project.org/xml/1.7.1/grampsxml.dtd">
<database xmlns="http://gramps-project.org/xml/1.7.1/">
  <header>
    <created date="2019-03-09" version="4.2.8"/>
    <researcher>
    </researcher>
  </header>
  <objects>
    <object handle="_e21e77b318dcbf5114e53d2ccf" change="1553878032" id="O0002">
      <file src="/home/bart/Desktop/1px.gif" mime="image/gif" checksum="c4f9b77f41082b633d120e2915c1ea2e" description="1px"/>
    </object>
  </objects>
  <people>
    <person handle="_e1dd3ac2fa22e6fefa18f738bdd" change="1552126811" id="I0002">
    </person>
  </people>
  <places>
    <placeobj handle="_e1dd2fb639e3f04f8cfabaa7e8a" change="1552125653" id="P0002" type="Unknown">
    </placeobj>
  </places>
  <events>
    <event handle="_e1dd3ac2fa22e6fefa18f738bdd" change="1552126811" id="E0002">
      <type>Birth</type>
    </event>
  </events>
  <sources>
    <source handle="_e2b5e77b4cc5c91c9ed60a6cb39" change="1558277217" id="S0002">
      <stitle>A Whisper</stitle>
      <reporef hlink="_e2c257f50fd27b1c841d7497448" medium="Book"/>
    </source>
  </sources>
  <repositories>
    <repository handle="_e2c257f50fd27b1c841d7497448" change="1558277216" id="R0002">
      <rname>Library of Alexandria</rname>
    </repository>
  </repositories>
  <citations>
    <citation handle="_e2c25a12a097a0b24bd9eae5090" change="1558277266" id="C0002">
      <sourceref hlink="_e2b5e77b4cc5c91c9ed60a6cb39"/>
    </citation>
  </citations>
  <notes>
    <note handle="_e1cb35d7e6c1984b0e8361e1aee" change="1551643112" id="N0002" type="Transcript">
      <text></text>
    </note>
  </notes>
</database>
""".strip()
        with TemporaryDirectory() as working_directory_path_str:
            working_directory_path = Path(working_directory_path_str)
            gramps_family_tree_one_path = working_directory_path / 'one.xml'
            with open(gramps_family_tree_one_path, mode='w') as f:
                f.write(family_tree_one_xml)

            gramps_family_tree_two_path = working_directory_path / 'two.xml'
            with open(gramps_family_tree_two_path, mode='w') as f:
                f.write(family_tree_two_xml)

            with App() as app:
                app.project.configuration.extensions.add(ExtensionConfiguration(Gramps, True, GrampsConfiguration(
                    family_trees=ReactiveList([
                        FamilyTreeConfiguration(gramps_family_tree_one_path),
                        FamilyTreeConfiguration(gramps_family_tree_two_path),
                    ])
                )))
                await load(app)
            assert 'O0001' in app.project.ancestry.entities[File]
            assert 'O0002' in app.project.ancestry.entities[File]
            assert 'I0001' in app.project.ancestry.entities[Person]
            assert 'I0002' in app.project.ancestry.entities[Person]
            assert 'P0001' in app.project.ancestry.entities[Place]
            assert 'P0002' in app.project.ancestry.entities[Place]
            assert 'E0001' in app.project.ancestry.entities[Event]
            assert 'E0002' in app.project.ancestry.entities[Event]
            assert 'S0001' in app.project.ancestry.entities[Source]
            assert 'S0002' in app.project.ancestry.entities[Source]
            assert 'R0001' in app.project.ancestry.entities[Source]
            assert 'R0002' in app.project.ancestry.entities[Source]
            assert 'C0001' in app.project.ancestry.entities[Citation]
            assert 'C0002' in app.project.ancestry.entities[Citation]
            assert 'N0001' in app.project.ancestry.entities[Note]
            assert 'N0002' in app.project.ancestry.entities[Note]
