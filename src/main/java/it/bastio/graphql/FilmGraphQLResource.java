package it.bastio.graphql;

import io.smallrye.mutiny.Uni;
import it.bastio.model.Film;
import it.bastio.service.FilmService;
import jakarta.inject.Inject;
import org.eclipse.microprofile.graphql.*;

import java.util.List;

@GraphQLApi
public class FilmGraphQLResource {

    @Inject
    FilmService filmService;

    @Query
    public Uni<List<Film>> getFilms() {
        return filmService.getFilms();
    }

    @Query
    public Uni<Film> findFilmById(Integer id) {
        return filmService.getFilmById(id);
    }

    @Mutation
    public Uni<Film> addFilm(Film film) {
        return filmService.addFilm(film);
    }

    @Mutation
    public Uni<Film> patchFilm(@NonNull @Id Integer id, Film film, @DefaultValue("true") boolean patch) {
        return filmService.patchFilm(id, film, patch);
    }

    @Mutation
    public Uni<Film> removeFilm(Integer id) {
        return filmService.removeFilm(id);
    }
}
