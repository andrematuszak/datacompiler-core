# Fonts and licenses

The PDF renderers use five embedded TrueType files:

- Liberation Sans Regular, Bold, Italic, and Bold Italic for rebuilt text.
- DejaVu Sans as the fallback face used for metrics and rendering.

Their license notices are shipped beside the font files in
`src/datacompiler/backend/fonts/`. Liberation is distributed under SIL OFL 1.1;
DejaVu Sans carries the Bitstream Vera and Arev notices. The font name tables
also identify their copyright and license source. No font file is modified.

The repository previously carried 36 Marianne font files, but no code referenced
them. They have been removed from the distributable font set: the official State
brand guidance says Marianne is reserved for State use, and the DSFR repository
states that Marianne assets are subject to specific terms. Do not re-add these
files unless the project obtains permission that covers its intended use.

Upstream references:

- [Liberation Fonts license](https://github.com/liberationfonts/liberation-fonts/blob/main/LICENSE)
- [DejaVu Fonts license](https://github.com/dejavu-fonts/dejavu-fonts/blob/master/LICENSE)
- [French State typography](https://www.info.gouv.fr/marque-de-letat/la-typographie)
- [DSFR use terms](https://github.com/GouvernementFR/dsfr#licence-et-droit-dutilisation)
