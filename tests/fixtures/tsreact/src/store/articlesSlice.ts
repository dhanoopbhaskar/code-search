export type Article = { id: number; title: string };

export const loadArticles = (): Article[] => [
  { id: 1, title: 'First' },
  { id: 2, title: 'Second' },
];

export const fetchArticles = () => async (dispatch: (value: Article[]) => void) => {
  dispatch(loadArticles());
};
