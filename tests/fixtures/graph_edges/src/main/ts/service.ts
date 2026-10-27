import { TsApi } from "./api";
import { TsArticle } from "./article";
import { TsRepo } from "./repo";

export class TsService implements TsApi {
  private repo: TsRepo;

  constructor(repo: TsRepo) {
    this.repo = repo;
  }

  run(article: TsArticle): void {
    this.repo.save(article);
  }
}
