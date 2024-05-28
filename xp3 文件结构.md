## xp3 文件结构

### ● 前言

我找来找去都没找到关于吉里吉里生成的 xp3 文件结构的说明，所以在这里记录一下。2.30 版本之后，xp3 的头部结构发生了一些变化，导致现有的工具（例如
xp3dec.exe）无法解压缩。不过，变化并不大，稍微修改一下就能解决。
顺便一提，源代码可以参考以下链接：

* [吉里吉里2.28版本源代码](https://sv.kikyou.info/trac/kirikiri/browser/kirikiri2/branches/2.28stable/kirikiri2/src/tools/win32/krdevui/RelSettingsUnit.cpp)
* [吉里吉里2.30版本源代码](https://sv.kikyou.info/trac/kirikiri/browser/kirikiri2/branches/2.30stable/kirikiri2/src/tools/win32/krdevui/RelSettingsUnit.cpp)

我之所以要调查这些，是因为我不小心把以前制作的游戏备份数据弄丢了，不得不从 xp3 文件中提取原始数据。我理解为什么吉里吉里/KAG
默认没有提供这样的工具。

### ● 文件结构概述

吉里吉里的数据文件 xp3 大致可以分为以下三个部分：

1. XP3 头部
2. 数据部分
3. 文件管理部分

每个部分的结构都非常简单，只要看一下源代码就能明白。不过，反复查看源代码很麻烦，所以为了方便自己，我决定在这里记录下来。

顺便一提，请注意，所有数值数据（如“大小”）**均以小端序存储**。

### ● XP3 头部

XP3 头部在吉里吉里2.28 和 2.30 版本中有所不同。具体来说，2.30
版本在中间插入了一个“缓冲区”。我不清楚为什么要这样改，但可以通过文件开头第12个字节开始是否是 `17 00 00 00 00 00 00 00`
来区分版本。

<table>
<tbody><tr>
  <th colspan="5">吉里吉里2.28及以前版本</th>
  <th colspan="5">吉里吉里2.30及以后版本</th>
</tr>
<tr>
  <th>部分名称</th>
  <th>数据名称</th><th>字节数</th><th>数据示例(十六进制)</th><th>备注</th>
  <th>部分名称</th>
  <th>数据名称</th><th>字节数</th><th>数据示例(十六进制)</th><th>备注</th>
</tr>
<tr>
  <td rowspan="10">XP3 头部</td>
  <td>XP3 头部1</td><td align="right">8</td><td>58 50 33 0d 0a 20 0a 1a</td><td>固定值</td>
  <td colspan="5" align="center">←相同</td>
</tr>
<tr>
  <td>XP3 头部2</td><td align="right">3</td><td>8b 67 01</td><td>固定值</td>
  <td colspan="5" align="center">←相同</td>
</tr>
<tr>
  <td colspan="4" align="center">无</td>
  <td rowspan="4">缓冲区</td>
  <td>缓冲区索引</td><td align="right">8</td><td>17 00 00 00 00 00 00 00</td><td>固定值</td>
</tr>
<tr>
  <td colspan="4" align="center">无</td>
  <td>头部次版本号</td><td align="right">4</td><td>01 00 00 00 </td><td>当前为固定值</td>
</tr>
<tr>
  <td colspan="4" align="center">无</td>
  <td>缓冲区头部</td><td align="right">1</td><td>80</td><td>固定值</td>
</tr>
<tr>
  <td colspan="4" align="center">无</td>
  <td>索引大小</td><td align="right">8</td><td>00 00 00 00 00 00 00 00</td><td>当前固定为0</td>
</tr>

  <tr><td>文件管理部分索引</td><td align="right">8</td><td align="center">-</td><td>文件管理部分在XP3文件中的位置</td>
  <td colspan="5" align="center">←相同</td>
</tr>
</tbody></table>

### ● 数据部分

数据部分实际上只有数据的排列，没有其他信息。
数据的存储范围由后面的文件管理部分定义，这里就不再赘述。

### ● 文件管理部分

文件管理部分在吉里吉里2.28 和 2.30 版本中是相同的。
它是一个文件信息的数组。但是，需要注意的是，一个管理部分包含多个 28 字节的段，因此数组的元素大小并不固定。此外，部分内容可能被压缩。
压缩使用的是 zlib，可以直接使用 zlib 的 `uncompress()` 函数解压。

文件管理部分的排列如下：

1. 文件管理部分头部 (1 个)
2. 文件管理部分 xN (每个部分包含多个段管理部分)

<table>
<tbody><tr><th colspan="4">文件管理部分头部</th></tr>
<tr>
  <th>数据名称</th><th>字节数</th><th>数据示例(十六进制)</th><th>备注</th>
</tr>
  <tr><td>压缩标志</td><td align="right">1</td><td align="center">-</td><td>0 = 管理部分未压缩<br>1 = 管理部分已压缩</td>
</tr>
<tr>
  <td>压缩管理部分大小</td><td align="right">8</td><td align="center">-</td><td>管理部分未压缩时不存在</td>
</tr>
<tr>
  <td>管理部分大小</td><td align="right">8</td><td align="center">-</td><td>如果已压缩，则为解压后的大小</td>
</tr>
<tr><td colspan="4" align="center">此处为文件管理部分数组 (压缩时为zlib压缩后的数据)</td></tr>
</tbody></table>

<table>
<tbody><tr><th colspan="5">文件管理部分 (一个)</th></tr>
<tr>
  <th>部分名称</th>
  <th>数据名称</th><th>字节数</th><th>数据示例(十六进制)</th><th>备注</th>
</tr>
<tr>
  <td rowspan="2">File</td>
  <td>管理部分头部</td><td align="right">4</td><td>字符串"File"</td><td>固定值</td>
</tr>
<tr>
  <td>此管理部分的大小</td><td align="right">8</td><td align="center">-</td><td>此后的数据大小，不包括"File"和“此管理部分的大小”本身</td>
</tr>
<tr>
  <td rowspan="7">Info</td>
  <td>info头部</td><td align="right">4</td><td>字符串"info"</td><td>固定值</td>
</tr>
<tr>
  <td>info大小</td><td align="right">8</td><td align="center">-</td><td>4+8+8+2+文件名长度*2，即到下一个Segment为止的字节数</td>
</tr>
<tr>
  <td>标志</td><td align="right">4</td><td align="center">-</td><td>0 = 无保护<br>1&lt;&lt;31 = 有保护<br>
“保护”是指“希望不要解压此数据”的标志，实际上并没有对数据进行任何修改。这是一种君子协定。
<a href="http://devdoc.kikyou.info/tvp/docs/kr2doc/contents/Releaser.html">
相关说明</a>。
</td>
</tr>
<tr>
  <td>解压后的文件大小</td><td align="right">8</td><td align="center">-</td><td align="center">-</td>
</tr>
<tr>
  <td>存储的文件大小</td><td align="right">8</td><td align="center">-</td><td align="center">-</td>
</tr>
<tr>
  <td>文件名长度</td><td align="right">2</td><td align="center">-</td><td>wchar类型，注意是/2后的值 (例如0x0b表示下面的文件名长度为22字节)</td>
</tr>
<tr>
  <td>文件名</td><td align="right">文件名长度决定</td><td>"s.y.s.t.e.m./.C.o.n.f.i.g...t.j.s."</td><td>WString类型 (不包含末尾的'\0')。此外，文件名是相对路径，包含目录名。请注意，目录分隔符是'/'而不是'\'。</td>
</tr>
<tr>
  <td rowspan="3">Segment</td>
  <td>segment头部</td><td align="right">4</td><td>字符串"segm"</td><td>固定值</td>
</tr>
<tr>
  <td>segment大小</td><td align="right">8</td><td align="center">-</td><td>段数*28 (一个段管理部分=28字节)</td>
</tr>
<tr>
  <td colspan="4" align="center">此处为重复的段管理部分，数量为段数</td>
</tr>
<tr>
  <td rowspan="3">Adler-32</td>
  <td>Adler ID</td><td align="right">4</td><td>字符串"adlr"</td><td>固定值</td>
</tr>
<tr>
  <td>Adler长度</td><td align="right">8</td><td>04 00 00 00 00 00 00 00</td><td>目前Adler长度固定为4字节，所以此处固定为4</td>
</tr>
<tr>
  <td>Adler-32</td><td align="right">4</td><td align="center">-</td><td>Adler-32 校验和 (<a href="http://ja.wikipedia.org/wiki/Adler-32">维基百科</a>)</td>
</tr>
</tbody></table>

“段”有多个意味着一个文件被分割成多部分存储。不过，实际上很少会被分割成多个段。每个段都可以分别指定压缩或不压缩，如果已压缩，则数据同样使用
zlib 压缩。

<table>
<tbody><tr><th colspan="4">段管理部分 (一个) 28字节</th></tr>
<tr>
  <th>数据名称</th><th>字节数</th><th>数据示例(十六进制)</th><th>备注</th>
</tr>
<tr>
  <td>标志</td><td align="right">4</td><td align="center">-</td><td>0 = 未压缩<br>1 = 已压缩</td>
</tr>
<tr>
  <td>偏移量</td><td align="right">8</td><td align="center">-</td><td>数据在XP3文件中的起始位置</td>
</tr>
<tr>
  <td>原始大小</td><td align="right">8</td><td align="center">-</td><td>数据的原始大小</td>
</tr>
<tr>
  <td>存储大小</td><td align="right">8</td><td align="center">-</td><td>数据在XP3文件中存储的大小。如果已压缩，则小于原始大小，如果未压缩，则与上面的“原始大小”相同</td>
</tr>
</tbody></table>

Adler-32 是一个简单的校验和，类似于 md5sum。可以忽略它。实际上，有些数据中并没有这个值。
它似乎是最近才添加的。也就是说，将来管理部分的区段（也称为块）可能会扩展和添加。
文件管理部分的每个区段开头都是以下结构：

1. 4 字节：头部字符串
2. 8 字节：此区段的大小（不包括开头 12 字节）
3. 区段内数据

因此，最好使用以下处理方式：
“读取 1. 和 2.，如果是未知的区段，则跳过”。
虽然不能保证这种方式在将来也能正常工作，但至少更容易扩展。

## ● 所以

我<a href="http://keepcreating.g2.xrea.com/krkrplugins/xp3ext/xp3ext.zip">做了一个工具</a>。不过只能在 cygwin 下使用，不知道谁会用。
我没有 Windows 下的 C 语言开发环境。我希望在写了这份说明并公开了工具的源代码之后，有人能做出更好的工具。

