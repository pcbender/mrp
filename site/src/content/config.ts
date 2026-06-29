import { defineCollection, z } from "astro:content";

const reviews = defineCollection({
  type: "content",
  schema: z.object({
    track_id: z.string(),
    impression: z.string().optional(),
    verdict_rank: z.number().optional(),
    verdict_label: z.string().optional(),
  }),
});

export const collections = { reviews };
