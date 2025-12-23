package it.michele.watchlog;

import io.quarkus.test.junit.QuarkusTest;
import it.michele.watchlog.model.Film;
import it.michele.watchlog.service.FilmService;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

@QuarkusTest
public class FilmTest {

    private static final String ACE_VENTURA = "Ace ventura";

    @Inject
    FilmService filmService;

    @Test
    void testCreateFilm(){
        filmService.create(new Film(ACE_VENTURA))
                .await()
                .indefinitely();

//        System.out.printf("film:\n%s%n", film);
//        assertEquals("Star wars", film.getTitle());
    }

    @Test
    void testGetFilm(){
        Film film = filmService.findById(1)
                .await()
                .indefinitely();

        System.out.printf("film:\n%s%n", film);
        assertEquals("Star wars", film.getTitle());
    }
}
