import unittest

from collect import clean_title, normalized, soup


class TitleIdentityTests(unittest.TestCase):
    def test_utf8_landing_title(self):
        page = '<meta name="citation_title" content="…and the Cross-Section of Expected Returns">'
        self.assertEqual(soup(page.encode()).select_one('meta')['content'],
                         '…and the Cross-Section of Expected Returns')

    def test_mojibake_alias_deduplication(self):
        self.assertEqual(normalized('â€¦and the Cross-Section of Expected Returns'),
                         normalized('… and the Cross-Section of Expected Returns'))

    def test_markup_title(self):
        self.assertEqual(clean_title('<div>Portfolio <span>Choice</span></div>'), 'Portfolio Choice')


if __name__ == '__main__':
    unittest.main()
