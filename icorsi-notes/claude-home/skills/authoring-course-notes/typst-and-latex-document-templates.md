# Document templates for course notes

Both formats share the same visual language: dark navy box for H1, blue left-bar for H2, bold-italic for H3, and a `personal-addition` callout block for any content not from the professor / iCorsi.

## Placeholders (same for both formats)

| Placeholder | Example |
|---|---|
| `SUBJECT` | `Algebra Lineare` |
| `CHAPTERS_LABEL` | `Capitoli 4-6` |
| `LANG` | `it` (Italian) / `en` (English) |
| `SUBTITLE_TOPICS` | `Funzioni Lineari · Applicazioni · Sistemi Dinamici Discreti` |
| `YEAR` | `2025/26` |

---

## Typst template

Paste verbatim at the top of every `.typ` notes file; replace the placeholders:

```typst
#set document(title: "SUBJECT - Note di Studio")
#set page(
  margin: (x: 2.5cm, y: 2.8cm),
  numbering: "1",
  number-align: center,
  header: context {
    if counter(page).get().first() > 2 {
      text(size: 9pt, fill: luma(120))[SUBJECT - Note di Studio · SUPSI]
      h(1fr)
      text(size: 9pt, fill: luma(120))[CHAPTERS_LABEL]
      line(length: 100%, stroke: 0.3pt + luma(180))
    }
  },
)
#set text(font: "New Computer Modern", size: 11pt, lang: "LANG")
#set par(justify: true, leading: 0.72em)
#set math.equation(numbering: none)
#set heading(numbering: "1.")
#set list(indent: 1em)
#set enum(indent: 1em)

#show heading.where(level: 1): it => {
  v(1.2em)
  block(
    width: 100%,
    fill: rgb("#1a1a2e"),
    inset: (x: 14pt, y: 10pt),
    radius: 6pt,
    text(fill: white, size: 15pt, weight: "bold", it),
  )
  v(0.6em)
}

#show heading.where(level: 2): it => {
  v(1.2em)
  block(
    stroke: (left: 3pt + rgb("#3a7bd5")),
    inset: (left: 10pt, y: 5pt),
    text(size: 12.5pt, weight: "bold", it),
  )
  v(0.3em)
}

#show heading.where(level: 3): it => {
  v(0.9em)
  text(size: 11pt, weight: "bold", style: "italic", it)
  v(0.2em)
}

// Highlight a key result inline
#let res(m) = text(fill: green, m)

// Non-course material - extra explanations, calculations, examples not from the professor
#let personal-addition(corpo) = block(
  fill: rgb("F0F8FF"),
  stroke: (left: 3pt + rgb("0077AA")),
  inset: 10pt,
  [
    #text(fill: rgb("0077AA"), weight: "bold")[Aggiunta personale:] \
    #corpo
  ],
)

// ── Title page ────────────────────────────────────────────────
#align(center)[
  #v(3.5cm)
  #text(size: 28pt, weight: "bold")[SUBJECT]
  #v(0.4em)
  #text(size: 17pt, weight: "regular")[Note di Studio]
  #v(1.2em)
  #line(length: 55%, stroke: 0.7pt)
  #v(1em)
  #text(size: 12.5pt, style: "italic")[CHAPTERS_LABEL]
  #v(0.4em)
  #text(size: 11pt)[SUBTITLE_TOPICS]
  #v(2.5cm)
  #text(size: 10pt, fill: luma(100))[Basato sui materiali del corso · SUPSI · Anno Accademico YEAR]
]

#pagebreak()

#outline(title: [*Indice*], indent: auto, depth: 4)

#pagebreak()
```

**Usage example - personal addition:**
```typst
#personal-addition[
  Questa derivazione non è nelle slide: partiamo dalla definizione di rango
  e mostriamo perché il numero di pivot coincide con la dimensione dell'immagine.
  $
  "rank"(A) = dim("Im"(A)) = "numero di pivot"
  $
]
```

---

## LaTeX template

Paste verbatim as the preamble of every `.tex` notes file; replace the placeholders (same set). Close with `\end{document}` after the last section.

```latex
\documentclass[11pt,a4paper]{article}

% ── Encoding & language ───────────────────────────────────────
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[italian]{babel}          % change to [english] if needed

% ── Typography ───────────────────────────────────────────────
\usepackage{lmodern}
\usepackage{microtype}
\usepackage[margin=2.5cm, top=2.8cm, bottom=2.8cm]{geometry}
\usepackage{parskip}
\setlength{\parindent}{0pt}

% ── Math ─────────────────────────────────────────────────────
\usepackage{amsmath,amssymb,amsthm}
\usepackage{mathtools}

% ── Headers & footers ────────────────────────────────────────
\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\footnotesize\color{gray}SUBJECT\ -- Note di Studio $\cdot$ SUPSI}
\fancyhead[R]{\footnotesize\color{gray}CHAPTERS\_LABEL}
\fancyfoot[C]{\thepage}
\renewcommand{\headrulewidth}{0.3pt}
% suppress header on title page and TOC
\fancypagestyle{plain}{\fancyhf{}\fancyfoot[C]{\thepage}\renewcommand{\headrulewidth}{0pt}}

% ── Section styling ──────────────────────────────────────────
\usepackage{titlesec}
\usepackage{xcolor}

\definecolor{headingbg}{HTML}{1a1a2e}
\definecolor{accentblue}{HTML}{3a7bd5}
\definecolor{pablock}{HTML}{F0F8FF}
\definecolor{paborder}{HTML}{0077AA}

% Level 1: dark box with white text
\titleformat{\section}
  {\normalfont}
  {\thesection}{0pt}
  {\colorbox{headingbg}{\parbox{\dimexpr\linewidth-2\fboxsep}{\color{white}\bfseries\large #1}}}
\titlespacing{\section}{0pt}{1.2em}{0.6em}

% Level 2: left blue bar
\titleformat{\subsection}[block]
  {\normalfont\bfseries\color{black}}
  {\thesubsection}{0.5em}{\leavevmode\llap{\color{accentblue}\vrule width 3pt height 1.1em depth 0.3em\hspace{7pt}}}
\titlespacing{\subsection}{10pt}{1.2em}{0.3em}

% Level 3: bold italic
\titleformat{\subsubsection}
  {\normalfont\bfseries\itshape}
  {\thesubsubsection}{0.5em}{}
\titlespacing{\subsubsection}{0pt}{0.9em}{0.2em}

% ── Hyperlinks & TOC ─────────────────────────────────────────
\usepackage[hidelinks]{hyperref}
\hypersetup{
  pdftitle={SUBJECT\ -- Note di Studio},
  pdfauthor={},
}

% ── Personal-addition environment ────────────────────────────
% Wraps any content NOT from the professor / NOT from iCorsi.
% Use for extra explanations, expanded calculations, self-constructed
% examples, analogies - anything you cannot cite back to a slide or PDF.
\usepackage{mdframed}
\newmdenv[
  backgroundcolor=pablock,
  linecolor=paborder,
  linewidth=3pt,
  topline=false, rightline=false, bottomline=false,
  innerleftmargin=10pt, innerrightmargin=10pt,
  innertopmargin=8pt, innerbottommargin=8pt,
]{personaladdition}
\newcommand{\personaladditionlabel}{%
  \textcolor{paborder}{\textbf{Aggiunta personale:}}%
}

% ── Inline result highlight ──────────────────────────────────
\newcommand{\res}[1]{\textcolor{green!60!black}{#1}}

% ── Lists ────────────────────────────────────────────────────
\usepackage{enumitem}
\setlist[itemize]{leftmargin=1em}
\setlist[enumerate]{leftmargin=1em}

\begin{document}

% ── Title page ───────────────────────────────────────────────
\begin{titlepage}
\centering
\vspace*{3.5cm}
{\fontsize{28}{34}\selectfont\bfseries SUBJECT\par}
\vspace{0.4em}
{\large Note di Studio\par}
\vspace{1.2em}
\rule{0.55\linewidth}{0.7pt}\par
\vspace{1em}
{\large\itshape CHAPTERS\_LABEL\par}
\vspace{0.4em}
{\normalsize SUBTITLE\_TOPICS\par}
\vspace{2.5cm}
{\small\color{gray}Basato sui materiali del corso $\cdot$ SUPSI $\cdot$ Anno Accademico YEAR\par}
\end{titlepage}

\tableofcontents
\newpage

% ── Body starts here ─────────────────────────────────────────
```

**Usage example - personal addition:**
```latex
\begin{personaladdition}
\personaladditionlabel\\
Questa derivazione non è nelle slide: partiamo dalla definizione di rango
e mostriamo perché il numero di pivot coincide con la dimensione dell'immagine.
\[
  \operatorname{rank}(A) = \dim(\operatorname{Im}(A)) = \text{numero di pivot}
\]
\end{personaladdition}
```
