import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';
import type { APIContext } from 'astro';

export async function GET(context: APIContext) {
  const papers = (await getCollection('papers', ({ data }) => !data.draft))
    .sort(
      (a, b) => b.data.publishedDate.valueOf() - a.data.publishedDate.valueOf()
    );

  return rss({
    title: 'The Daily Paper',
    description: 'One technical paper, explained properly, every morning.',
    site: context.site ?? 'https://example.com',
    items: papers.map((paper) => {
      const slug = paper.slug.replace(/^\d{4}-\d{2}-\d{2}-/, '');
      return {
        title: paper.data.title,
        pubDate: paper.data.publishedDate,
        description: paper.data.tldr,
        link: `/papers/${slug}/`,
        categories: [paper.data.primaryCategory, ...paper.data.tags],
        author: paper.data.authors.join(', '),
      };
    }),
    customData: '<language>en-us</language>',
  });
}
