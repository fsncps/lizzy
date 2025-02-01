from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, Container
from textual.widgets import Tree, Header, Markdown, Static, Input, OptionList
from textual.screen import Screen
import httpx
import xml.etree.ElementTree as ET
import os
import json
import datetime
from textual.events import Key
from pathlib import Path

DEBUG_LOG_FILE = Path(__file__).resolve().parent.parent / "var" / "britannica_debug.log"  # Change this path if needed

WORDS_API_KEY = os.getenv("WORDS_API_KEY")
MERRIAM_WEBSTER_KEY =  os.getenv("MERRIAM_WEBSTER_KEY")
MERRIAM_WEBSTER_URL = "https://www.dictionaryapi.com/api/v3/references/collegiate/json/"
WORDS_API_URL = "https://wordsapiv1.p.rapidapi.com/words/"
HEADERS = {"X-RapidAPI-Key": WORDS_API_KEY, "X-RapidAPI-Host": "wordsapiv1.p.rapidapi.com"}
EB_API_KEY = os.getenv("EB_API_KEY", "").strip()


class DashboardScreen(Screen):
    """Screen for navigating records."""

    CSS_PATH = "main.css"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.output_buffer = []
        self.max_output_lines = 6  # Maximum number of lines in the output widget

    def on_mount(self):
        self.eb_articles = self.load_eb_articles()  # Load articles on startup

    def load_eb_articles(self):
        """Load Britannica articles from local JSON."""
        try:
            ARTICLES_FILE = Path(__file__).resolve().parent.parent / "var" / "articles.json"

            with open(ARTICLES_FILE, "r") as f:
                articles = json.load(f)  # ✅ Correct JSON reading

            # Debug: Print first 5 articles
            print(f"✅ Loaded {len(articles)} articles from JSON.")
            for a in articles[:5]:  # Print sample articles
                print(f"📝 {a['title']} (ID: {a['articleId']})")

            return {a["title"].lower(): a["articleId"] for a in articles}
        
        except Exception as e:
            self.append_output(f"❌ Error loading EB articles: {e}")
            return {}

    def compose(self) -> ComposeResult:
        """Compose the layout."""
        yield Header()
        yield Horizontal(
            Vertical(
                Container(Input("Enter word", id="words-input"), id="input-pane", classes="Input"),
                Container(Tree("Words Tree", id="words-tree", classes="TextFields"), id="tree-pane", classes="Panes"),
                Container(OptionList("EB List", id="eb-list", classes="TextFields"), id="eb-list", classes="Panes"),
                Container(Static("", id="output-static"), id="output-pane", classes="Panes"),
                id="left-panel", classes="panels"
            ),
            Vertical(
                Container(Markdown("**dictionary entry here**", id="dict-md", classes="TextFields"), id="dict-pane", classes="Panes"),
                Container(Markdown("**Encyclopedia Britannica entry here**", id="EB-md", classes="TextFields"), id="EB-pane", classes="Panes"),
                id="right-panel", classes="Panels"
            )
        )

    def search_britannica_titles(self, keyword: str):
        """Search Britannica titles locally and update the OptionList."""
        keyword = keyword.lower()
        results = {title: aid for title, aid in self.eb_articles.items() if keyword in title}

        # Debugging output
        self.append_output(f"🔍 Searching '{keyword}' in Britannica articles.")
        self.append_output(f"✅ Found {len(results)} matches.")  # Should show >0 if found

        eb_list = self.query_one("#eb-list", OptionList)
        eb_list.clear_options()

        if results:
            for title, article_id in results.items():
                print(f"📌 Adding to EB List: {title} (ID: {article_id})")  # Debugging
                eb_list.add_option(f"ID: {article_id} - {title}")
            self.append_output(f"📚 Found {len(results)} Britannica articles.")
        else:
            eb_list.add_option("❌ No matching articles found.")
            self.append_output("❌ No Britannica matches.")


    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handles input submission for word search."""
        word = event.value.strip()
        if word:
            print(f"🟢 Input submitted: {word}")  # Debugging

            # Query WordsAPI & Dictionary
            await self.query_wordsapi(word)
            await self.query_dictionary(word)

            # Search Britannica titles locally
            print("🔍 Triggering Britannica search...")  # Debugging
            self.search_britannica_titles(word)

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handles selection of an EB article from the list."""
        selected = event.option.prompt.strip()  # ✅ Extract text properly
        
        if selected.startswith("ID: "):
            article_id = selected.split(" - ")[0].replace("ID: ", "").strip()
            self.append_output(f"📖 Fetching Britannica article: {article_id}")
            
            # Fetch article content
            eb_content = await self.get_eb_article(article_id)
            
            # Display in Markdown container
            self.update_eb_display(eb_content)
        else:
            self.append_output("⚠️ Invalid selection in EB list.")


    async def query_wordsapi(self, word: str):
        """Fetch word details from WordsAPI and populate the tree."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{WORDS_API_URL}{word}", headers=HEADERS)
            if response.status_code == 200:
                data = response.json()
                await self.update_tree(data)
            else:
                await self.update_tree({"error": "Word not found"})

    async def update_tree(self, data: dict):
        """Update the tree view with the retrieved data."""
        tree = self.query_one("#words-tree", Tree)
        tree.clear()

        # Ensure a root node exists
        if tree.root is None:
            root = tree.set_root("Word Details")
        else:
            root = tree.root.add("Word Details")

        self.build_tree(root, data)

        # Expand all child nodes under the root
        if root:  # Ensure root exists before accessing children
            for node in root.children:
                node.expand()

        self.append_output(f"Updating tree with data: {data.get('word', 'Unknown')}")
        self.refresh()  # Ensure UI updates

    
    def build_tree(self, parent, data):
        """Build the tree with structured formatting."""
        if "results" not in data:
            parent.add("No definitions found.")
            return

        grouped_results = {}
        
        # Group results by partOfSpeech
        for entry in data["results"]:
            pos = entry.get("partOfSpeech", "unknown")
            if pos not in grouped_results:
                grouped_results[pos] = []
            grouped_results[pos].append(entry)

        # Add each part of speech as a collapsible node
        for pos, entries in grouped_results.items():
            pos_node = parent.add(pos.capitalize())  # "Noun", "Verb", etc.
            
            # Add each definition as a collapsible node under the part of speech
            for i, entry in enumerate(entries, 1):
                definition_text = entry["definition"]
                definition_node = pos_node.add(f"{pos[:1]}{i}: {definition_text}")  # "n1", "v1" etc.
                
                # Add subcategories under the definition
                for key in ["synonyms", "typeOf", "hasTypes", "hasInstances", "antonyms", "derivation", "examples"]:
                    if key in entry:
                        values = entry[key]
                        if values:
                            sub_node = definition_node.add(key.replace("has", "Has ").replace("typeOf", "Type of").capitalize())  # Pretty label
                            for value in values:
                                sub_node.add(str(value))

                # If no sub-items, prevent expansion
                if not definition_node.children:
                    definition_node.allow_expand = False

            # If no definitions, prevent expansion
            if not pos_node.children:
                pos_node.allow_expand = False


    def append_output(self, message, style=None):
        """Append debugging output both to the UI and a log file."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"

        # Maintain buffer in UI
        self.output_buffer.append(message)
        if len(self.output_buffer) > self.max_output_lines:
            self.output_buffer.pop(0)

        # Update the output widget
        output_pane = self.query_one("#output-static", Static)
        output_pane.update("\n".join(self.output_buffer))

        # Write log to file
        with open(DEBUG_LOG_FILE, "a") as log_file:
            log_file.write(log_message)    

    async def query_dictionary(self, word: str):
        """Fetch word details from Merriam-Webster API and update dictionary markdown."""
        url = f"{MERRIAM_WEBSTER_URL}{word}?key={MERRIAM_WEBSTER_KEY}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url)

        if response.status_code == 200:
            data = response.json()
            formatted_entry = self.format_dictionary_entry(data)
            self.update_dictionary_display(formatted_entry)
        else:
            self.update_dictionary_display("❌ Dictionary entry not found.")

    def format_dictionary_entry(self, data):
        """Format dictionary API response into readable Markdown with expanded details."""
        if not data or not isinstance(data, list) or not isinstance(data[0], dict):
            return "No dictionary entry found."

        entries = []
        for entry in data:
            word = entry.get("hwi", {}).get("hw", "").replace("*", "")  # Headword
            part_of_speech = entry.get("fl", "Unknown")
            definitions = entry.get("shortdef", [])
            synonyms = entry.get("meta", {}).get("syns", [])
            etymology = entry.get("et", [])
            first_use = entry.get("date", "Unknown")

            # Extract Example Sentences Safely
            example_sentences = []
            senses = entry.get("def", [{}])[0].get("sseq", [])
            for sense in senses:
                for sub_sense in sense:
                    if isinstance(sub_sense, list) and len(sub_sense) > 1 and isinstance(sub_sense[1], dict):
                        dt = sub_sense[1].get("dt", [])
                        for item in dt:
                            if item[0] == "vis" and isinstance(item[1], list):
                                example_sentences.extend([ex.get("t", "") for ex in item[1] if isinstance(ex, dict)])


            examples_text = "\n".join(f"- _{ex}_" for ex in example_sentences) if example_sentences else "None"

            # Format Definitions
            definition_text = "\n".join(f"- {d}" for d in definitions) if definitions else "- No definitions found."

            # Format Synonyms
            synonym_text = ", ".join([syn for group in synonyms for syn in group]) if synonyms else "None"

            # Format Etymology
            etymology_text = " ".join([" ".join(ety) for ety in etymology]) if etymology else "Unknown"

            # Combine all extracted info
            entry_text = (
                f"### {word} ({part_of_speech})\n"
                f"**Definitions:**\n{definition_text}\n\n"
                f"**Synonyms:** {synonym_text}\n\n"
                f"**Etymology:** {etymology_text}\n\n"
                f"**First Known Use:** {first_use}\n\n"
                f"**Examples:**\n{examples_text}"
            )

            entries.append(entry_text)

        return "\n\n".join(entries)


    def update_dictionary_display(self, content: str):
        """Update the dictionary markdown widget."""
        dict_md = self.query_one("#dict-md", Markdown)
        dict_md.update(content)
    
    async def get_eb_article(self, article_id: str):
        """Fetch and parse an article from Britannica API."""
        article_url = f"https://syndication.api.eb.com/production/article/{article_id}/xml"

        self.append_output(f"📡 Fetching Britannica Article from: {article_url}")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(article_url, headers={"x-api-key": EB_API_KEY})

            self.append_output(f"📡 Britannica Article Response Code: {response.status_code}")

            if response.status_code != 200:
                self.append_output(f"❌ Britannica Article Fetch Error: {response.status_code} - {response.text}")
                return "❌ No Britannica entry found."

            try:
                return self.parse_eb_article(response.text)
            except Exception as e:
                self.append_output(f"❌ Britannica XML Parsing Error: {e}")
                return "❌ Error parsing Britannica entry."

    def parse_eb_article(self, xml_content: str):
        """Convert Britannica XML response into readable Markdown."""
        try:
            root = ET.fromstring(xml_content)

            # Extract title
            title_elem = root.find(".//title")
            title = title_elem.text if title_elem is not None else "Unknown Title"
            self.append_output(f"📖 Britannica Title: {title}")

            # Extract all paragraphs and concatenate text correctly
            paragraphs = []
            for para in root.findall(".//p"):
                text_parts = [para.text] if para.text else []
                
                # Handle <e> (emphasis), <xref> (cross-references), and inline elements
                for child in para:
                    if child.tag == "e" and child.text:  # Bold/Italic text
                        text_parts.append(f"**{child.text}**")
                    elif child.tag == "xref" and child.text:  # Cross-references
                        text_parts.append(f"[{child.text}](#)")

                    if child.tail:
                        text_parts.append(child.tail)

                # Combine text and add to paragraph list
                paragraphs.append(" ".join(filter(None, text_parts)))

            # Format into Markdown
            content = f"### {title}\n\n" + "\n\n".join(paragraphs)

            return content

        except Exception as e:
            self.append_output(f"❌ Britannica XML Parsing Error: {e}")
            return "❌ Error parsing Britannica entry."

    #
    # async def get_eb_article_id(self, word: str):
    #     """Search Britannica for an article ID."""
    #     search_url = f"https://encyclopaediaapi.com/api/v1/articles?query={word}&api_key={EB_API_KEY}"
    #     
    #     self.append_output(f"🔍 Britannica Search URL: {search_url}")
    #
    #     async with httpx.AsyncClient(follow_redirects=True) as client:  # Enable redirect following
    #         response = await client.get(search_url)
    #
    #         self.append_output(f"📡 Britannica API Response Code: {response.status_code}")
    #         self.append_output(f"📡 Britannica Headers: {response.headers}")
    #
    #         if response.status_code == 302:  # Redirect handling
    #             redirected_url = response.headers.get("Location", "Unknown")
    #             self.append_output(f"🔀 Britannica Redirecting To: {redirected_url}")
    #
    #         if response.status_code != 200:
    #             self.append_output(f"❌ Britannica API Error: {response.status_code} - {response.text}")
    #             return None
    #
    #         try:
    #             data = response.json()
    #             self.append_output(f"📡 Britannica API Response Data: {data}")
    #
    #             if isinstance(data, list) and len(data) > 0:
    #                 article_id = data[0].get("article_id")
    #                 self.append_output(f"📄 Britannica Found Article ID: {article_id}")
    #                 return article_id
    #
    #         except Exception as e:
    #             self.append_output(f"❌ Britannica JSON Error: {e}")
    #
    #     self.append_output("❌ No Britannica entry found.")
    #     return None
    #
    # async def get_eb_article(self, article_id: str):
    #     """Fetch and parse an article from Britannica."""
    #     article_url = f"https://encyclopaediaapi.com/api/v1/article/{article_id}/xml?api_key={EB_API_KEY}"
    #     
    #     self.append_output(f"📡 Fetching Britannica Article from: {article_url}")
    #
    #     async with httpx.AsyncClient(follow_redirects=True) as client:
    #         response = await client.get(article_url)
    #
    #         self.append_output(f"📡 Britannica Article Response Code: {response.status_code}")
    #         self.append_output(f"📡 Britannica Article Headers: {response.headers}")
    #
    #         if response.status_code == 302:
    #             redirected_url = response.headers.get("Location", "Unknown")
    #             self.append_output(f"🔀 Britannica Redirecting To: {redirected_url}")
    #
    #         if response.status_code != 200:
    #             self.append_output(f"❌ Britannica Article Fetch Error: {response.status_code} - {response.text}")
    #             return "❌ No Britannica entry found."
    #
    #         try:
    #             xml_preview = response.text[:500]  # Print only first 500 chars for debugging
    #             self.append_output(f"📄 Britannica XML Response (Preview): {xml_preview}")
    #             return self.parse_eb_article(response.text)
    #         except Exception as e:
    #             self.append_output(f"❌ Britannica XML Parsing Error: {e}")
    #             return "❌ Error parsing Britannica entry."
    #
    # def parse_eb_article(self, xml_content: str):
    #     """Convert Britannica XML response into readable Markdown."""
    #     try:
    #         root = ET.fromstring(xml_content)
    #
    #         # Extract title
    #         title_elem = root.find(".//title")
    #         title = title_elem.text if title_elem is not None else "Unknown Title"
    #         self.append_output(f"📖 Britannica Title: {title}")
    #
    #         # Extract summary
    #         summary_elem = root.find(".//summary")
    #         summary = summary_elem.text if summary_elem is not None else "No summary available."
    #         self.append_output(f"📖 Britannica Summary: {summary[:200]}")  # Limit length for debugging
    #
    #         # Extract first few paragraphs
    #         paragraphs = []
    #         for para in root.findall(".//p"):
    #             if para.text:
    #                 paragraphs.append(para.text)
    #                 if len(paragraphs) >= 3:  # Limit paragraphs for brevity
    #                     break
    #
    #         if paragraphs:
    #             self.append_output(f"📖 Britannica Extracted Paragraphs: {len(paragraphs)} found.")
    #         else:
    #             self.append_output("❌ No Britannica paragraphs extracted.")
    #
    #         # Format into Markdown
    #         content = f"### {title}\n\n**Summary:** {summary}\n\n" + "\n\n".join(paragraphs)
    #         
    #         return content
    #
    #     except Exception as e:
    #         self.append_output(f"❌ Britannica XML Parsing Exception: {e}")
    #         return "❌ Error parsing Britannica entry."
    #
    def update_eb_display(self, content: str):
        """Update the Encyclopedia Britannica markdown widget."""
        eb_md = self.query_one("#EB-md", Markdown)
        expandable_content = f"<details><summary>📘 Britannica Entry</summary>\n\n{content}\n\n</details>"
        eb_md.update(expandable_content)
    #
    # async def on_input_submitted(self, event: Input.Submitted) -> None:
    #     """Handle input submission by querying all sources."""
    #     word = event.value.strip()
    #     if word:
    #         self.append_output(f"🔎 Searching for: {word}")
    #
    #         await self.query_wordsapi(word)
    #         await self.query_dictionary(word)
    #
    #         self.append_output("📡 Starting Britannica search...")
    #         article_id = await self.get_eb_article_id(word)
    #         
    #         if article_id:
    #             self.append_output(f"📄 Britannica Article ID Found: {article_id}")
    #             eb_content = await self.get_eb_article(article_id)
    #             self.update_eb_display(eb_content)
    #         else:
    #             self.append_output("❌ No Britannica entry found.")
    #             self.update_eb_display("❌ No Britannica entry found.")
    #
    #
    # async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
    #     """Handle when a node is selected in the tree."""
    #     if not event.node or not event.node.label:
    #         self.append_output("⚠️ No valid selection.")
    #         return  # Ignore selection if nothing is selected
    #
    #     selected_text = str(event.node.label).strip()  # Convert to string safely
    #
    #     # Prevent selecting the root node (e.g., "Word Details")
    #     if selected_text.lower() in ["word details", "no definitions found"]:
    #         self.append_output("⚠️ Ignoring selection: Not a valid word.")
    #         return  
    #
    #     self.selected_word = selected_text  # Store the selected word globally
    #
    #     self.append_output(f"📌 Selected Node: {selected_text}")

        # Update the words input field
        # words_input = self.query_one("#words-input", Input)
        # words_input.value = selected_text  # Set the input box value
        # words_input.refresh()  # Ensure the UI updates

    async def on_key(self, event: Key) -> None:
        """Handle Enter for submission, but let Textual handle Space for expansion."""
        key = event.key.lower()
        tree = self.query_one("#words-tree", Tree)
        selected_node = tree.cursor_node  # Get the currently selected node

        if not selected_node or not selected_node.label:
            self.append_output("⚠️ No valid selection.")
            return  # Ignore keypress if nothing is selected

        selected_text = str(selected_node.label).strip()  # Ensure it's a string

        if key == "enter":
            self.selected_word = selected_text
            self.append_output(f"🔍 Submitting: {self.selected_word}")

            # Check if it's a Britannica article ID
            if self.selected_word.startswith("ID: "):
                article_id = self.selected_word.replace("ID: ", "").strip()
                self.append_output(f"📖 Fetching Britannica article: {article_id}")
                eb_content = await self.get_eb_article(article_id)
                self.update_eb_display(eb_content)

            else:
                # **Only refresh dictionary & tree when selecting a word, NOT an EB article**
                self.append_output(f"🔄 Restarting search for: {self.selected_word}")
                await self.query_wordsapi(self.selected_word)
                await self.query_dictionary(self.selected_word)

                # 📡 **Trigger Britannica search & update OptionList**
                self.search_britannica_titles(self.selected_word)
