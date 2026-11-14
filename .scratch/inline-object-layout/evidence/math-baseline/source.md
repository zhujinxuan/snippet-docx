# MATH-HEADING inline $\frac{a+b}{c+d}$ allocation

CONTROL-BEFORE ordinary non-math paragraph. This text must retain the house body leading and must not be reclassified as an equation.

INLINE-FRACTION 正文前 $\frac{\frac{a+b}{c+d}+e}{\frac{f+g}{h+i}+j}$ 正文后。This tall nested inline fraction shares its paragraph with ordinary text.

CONTROL-BETWEEN ordinary prose follows the inline fraction without an empty spacer paragraph in the document.

INLINE-SUPERSCRIPT-WRAPPED 正文前 $x^{n+1}+y^{2}+z^{k^{2}+1}$ 正文后。This deliberately long prose paragraph provides enough natural text for line wrapping at normal report page widths. Its equation stays inline, and its paragraph stays ordinary prose rather than becoming a display equation. Additional surrounding Chinese prose keeps the line allocation diagnostic independent of one short formula: 本段用于检查自然换行后的行距，公式前后均保留普通文字，连续多行仍属于同一正文段落。

DISPLAY-FRACTION-BEFORE ordinary neighboring prose.

$$\frac{\frac{a+b}{c+d}+e}{\frac{f+g}{h+i}+j}$$

DISPLAY-FRACTION-AFTER ordinary neighboring prose.

DISPLAY-MATRIX-BEFORE ordinary neighboring prose.

$$\begin{pmatrix}a & b \\ c & d \\ e & f\end{pmatrix}$$

DISPLAY-MATRIX-AFTER ordinary neighboring prose.

DISPLAY-OPERATORS-BEFORE ordinary neighboring prose.

$$\sum_{i=1}^{n} x_i + \int_{0}^{1} f(x)\,dx + \prod_{j=1}^{m} y_j$$

DISPLAY-OPERATORS-AFTER ordinary neighboring prose.

1. LIST-MATH inline $\frac{a+b}{c+d}$ retains ordered list numbering.
2. LIST-CONTROL plain non-math list item.

`anchor:begin:table`

| Case | Value |
|------|-------|
| TABLE-MATH | $\frac{a+b}{c+d}$ |
| TABLE-CONTROL | ordinary cell |

Table: TABLE-CAPTION-MATH inline $\frac{a+b}{c+d}$

`anchor:end:table`

`anchor:begin:figure`

![IMAGE-CAPTION-CONTROL preserved nearby image](../layout.png){width=10cm}

`anchor:end:figure`

CONTROL-AFTER ordinary non-math paragraph after the neighboring image and caption.
