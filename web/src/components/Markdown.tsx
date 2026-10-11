import MarkdownIt from "markdown-it";

// Raw HTML disabled; images disabled so viewing a record never fetches anything (PRD S3, P1).
const md = new MarkdownIt("commonmark", { html: false, linkify: false }).disable("image");

export function Markdown({ text }: { text: string }) {
  // markdown-it escapes all input when html is disabled, so this HTML is safe to insert.
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: md.render(text) }} />;
}
