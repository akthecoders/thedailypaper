import { defineCollection, z } from 'astro:content';

const papers = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    arxivId: z.string(),
    publishedDate: z.date(),
    paperDate: z.date(),
    primaryCategory: z.string(),
    pdfUrl: z.string().url(),
    absUrl: z.string().url(),
    pickReason: z.string(),
    tldr: z.string(),
    hook: z.string().optional(),
    authors: z.array(z.string()),
    tags: z.array(z.string()),
    draft: z.boolean().optional().default(false),
    videoUrl: z.string().url().optional(),
    videoPoster: z.string().url().optional(),
  }),
});

export const collections = { papers };
