"""FEA classes and miscellaneous functions.

Finite element classes:

* Tri6 (six-noded quadratic triangular element)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sectionproperties.pre.pre import Material


@dataclass
class Tri6:
    """Class for a six noded quadratic triangular element.

    Provides methods for the calculation of section properties based on the finite
    element method.

    Attributes:
        el_id: Unique element id
        coords: A ``2 x 6`` array of the coordinates of the Tri6 nodes. The first three
            columns relate to the vertices of the triangle and the last three columns
            correspond to the mid-nodes.
        node_ids: A list of the global node ids for the current element
        material: Material object for the current finite element
    """

    el_id: int
    coords: np.ndarray
    node_ids: list[int]
    material: Material

    # _m and _x0 are used for global coord to local coord mapping
    _m: np.ndarray = field(init=False)
    _x0: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        """Sets up the global to local mapping."""
        # Create a mapping from global elm to local elm (unit triangle)
        # The result is used in the global to local mapping:
        # (eta, xi) = _M(x_global-_x0), zeta = 1-eta-xi
        p0, p1, self._x0 = self.coords[:, 0:3].transpose()

        # Shift the triangle so the x_3 vertex (global) is on the origin
        # ((eta, xi, zeta) = (0,0,1))
        # Aside: This is chosen to be consistent with the shape function definitions.
        # At (0,0,1), N3=1, N1=N2=N4=...=0 (see Theoretical Background documentation)
        # since (x, y) = (sum(N_i(eta,xi,zeta)*x_i),  sum(N_i(eta,xi,zeta)*y_i)
        # then at (0,0,1): (x,y) = (x_3,y_3). ie: (x_3, y_3) => (0,0,1)
        r0 = p0 - self._x0
        r1 = p1 - self._x0

        # Asseble the equations to solve for the transformation for the unit triangle
        x = np.array([r0, r1]).transpose()
        b = np.array([[1, 0], [0, 1]])
        self._m = np.linalg.solve(x, b)

    def __repr__(self) -> str:
        """Object string representation."""
        rep = f"el_id: {self.el_id}\ncoords: {self.coords}\n"
        rep += f"node_ids: {self.node_ids}\nmaterial: {self.material}"
        return rep

    def geometric_properties(
        self,
    ) -> tuple[float, float, float, float, float, float, float, float, float]:
        """Calculates the geometric properties for the current finite element.

        Return:
            Tuple containing the geometric properties, and the elastic and shear moduli
            of the element: (``area``, ``qx``, ``qy``, ``ixx``, ``iyy``, ``ixy``, ``e``,
            ``g``, ``rho``)
        """
        # initialise geometric properties
        area: float = 0.0
        qx: float = 0.0
        qy: float = 0.0
        ixx: float = 0.0
        iyy: float = 0.0
        ixy: float = 0.0

        # Gauss points for 6 point Gaussian integration
        gps = gauss_points(n=6)

        # loop through each Gauss point
        for gp in gps:
            # determine shape function, shape function derivative and jacobian
            n, _, j = shape_function(coords=self.coords, gauss_point=gp)

            area += gp[0] * j
            qx += gp[0] * np.dot(n, np.transpose(self.coords[1, :])) * j
            qy += gp[0] * np.dot(n, np.transpose(self.coords[0, :])) * j
            ixx += gp[0] * np.dot(n, np.transpose(self.coords[1, :])) ** 2 * j
            iyy += gp[0] * np.dot(n, np.transpose(self.coords[0, :])) ** 2 * j
            ixy += (
                gp[0]
                * np.dot(n, np.transpose(self.coords[1, :]))
                * np.dot(n, np.transpose(self.coords[0, :]))
                * j
            )

        return (
            area,
            qx,
            qy,
            ixx,
            iyy,
            ixy,
            self.material.elastic_modulus,
            self.material.shear_modulus,
            self.material.density,
        )

    def torsion_properties(self) -> tuple[np.ndarray, np.ndarray]:
        """Calculates the element warping stiffness matrix and the torsion load vector.

        Return:
            Element stiffness matrix ``k_el`` and element torsion load vector ``f_el``
        """
        # initialise stiffness matrix and load vector
        k_el = np.empty(shape=(6, 6), dtype=float)
        f_el = np.empty(shape=(1, 6), dtype=float)

        # Gauss points for 6 point Gaussian integration
        gps = gauss_points(n=6)

        for gp in gps:
            # determine shape function, shape function derivative and jacobian
            n, b, j = shape_function(coords=self.coords, gauss_point=gp)

            # determine x and y position at Gauss point
            nx = np.dot(n, np.transpose(self.coords[0, :]))
            ny = np.dot(n, np.transpose(self.coords[1, :]))

            # calculated modulus weighted stiffness matrix and load vector
            k_el += (
                gp[0] * np.dot(np.transpose(b), b) * j * (self.material.elastic_modulus)
            )
            f_el += (
                gp[0]
                * np.dot(np.transpose(b), np.transpose(np.array([ny, -nx])))
                * j
                * self.material.elastic_modulus
            )

        return k_el, f_el

    def shear_load_vectors(
        self,
        ixx: float,
        iyy: float,
        ixy: float,
        nu: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Calculates the element shear load vectors for evaluating the shear functions.

        Args:
            ixx: Second moment of area about the centroidal x-axis
            iyy: Second moment of area about the centroidal y-axis
            ixy: Second moment of area about the centroidal xy-axis
            nu: Effective Poisson's ratio for the cross-section

        Return:
            Element shear load vector psi ``f_psi`` and phi ``f_phi``
        """
        # initialise force vectors
        f_psi = np.empty(shape=(1, 6), dtype=float)
        f_phi = np.empty(shape=(1, 6), dtype=float)

        # Gauss points for 6 point Gaussian integration
        gps = gauss_points(6)

        for gp in gps:
            # determine shape function, shape function derivative and jacobian
            n, b, j = shape_function(coords=self.coords, gauss_point=gp)

            # determine x and y position at Gauss point
            nx = np.dot(n, np.transpose(self.coords[0, :]))
            ny = np.dot(n, np.transpose(self.coords[1, :]))

            # determine shear parameters
            r = nx**2 - ny**2
            q = 2 * nx * ny
            d1 = ixx * r - ixy * q
            d2 = ixy * r + ixx * q
            h1 = -ixy * r + iyy * q
            h2 = -iyy * r - ixy * q

            f_psi += (
                gp[0]
                * (
                    nu
                    / 2
                    * np.transpose(np.transpose(b).dot(np.array([[d1], [d2]])))[0]
                    + 2 * (1 + nu) * np.transpose(b) * (ixx * nx - ixy * ny)
                )
                * j
                * self.material.elastic_modulus
            )
            f_phi += (
                gp[0]
                * (
                    nu
                    / 2
                    * np.transpose(np.transpose(b).dot(np.array([[h1], [h2]])))[0]
                    + 2 * (1 + nu) * np.transpose(n) * (iyy * ny - ixy * nx)
                )
                * j
                * self.material.elastic_modulus
            )

        return f_psi, f_phi

    def shear_warping_integrals(
        self,
        ixx: float,
        iyy: float,
        ixy: float,
        omega: np.ndarray,
    ) -> tuple[float, float, float, float, float, float]:
        """Calculates the element shear centre and warping integrals for shear analysis.

        Args:
            ixx: Second moment of area about the centroidal x-axis
            iyy: Second moment of area about the centroidal y-axis
            ixy: Second moment of area about the centroidal xy-axis
            omega: Values of the warping function at the element nodes

        Return:
            Shear centre integrals about the ``x`` and ``y`` axes and warping integrals
            (``sc_xint``, ``sc_yint``, ``q_omega``, ``i_omega``, ``i_xomega``,
            ``i_yomega``)
        """
        # initialise integrals
        sc_xint: float = 0
        sc_yint: float = 0
        q_omega: float = 0
        i_omega: float = 0
        i_xomega: float = 0
        i_yomega: float = 0

        # Gauss points for 6 point Gaussian integration
        gps = gauss_points(n=6)

        for gp in gps:
            # determine shape function, shape function derivative and jacobian
            n, _, j = shape_function(coords=self.coords, gauss_point=gp)

            # determine x and y position at Gauss point
            nx = np.dot(n, np.transpose(self.coords[0, :]))
            ny = np.dot(n, np.transpose(self.coords[1, :]))
            n_omega = np.dot(n, np.transpose(omega))

            sc_xint += (
                gp[0]
                * (iyy * nx + ixy * ny)
                * (nx**2 + ny**2)
                * j
                * self.material.elastic_modulus
            )
            sc_yint += (
                gp[0]
                * (ixx * ny + ixy * nx)
                * (nx**2 + ny**2)
                * j
                * self.material.elastic_modulus
            )
            q_omega += gp[0] * n_omega * j * self.material.elastic_modulus
            i_omega += gp[0] * n_omega**2 * j * self.material.elastic_modulus
            i_xomega += gp[0] * nx * n_omega * j * self.material.elastic_modulus
            i_yomega += gp[0] * ny * n_omega * j * self.material.elastic_modulus

        return sc_xint, sc_yint, q_omega, i_omega, i_xomega, i_yomega

    def shear_coefficients(
        self,
        ixx: float,
        iyy: float,
        ixy: float,
        psi_shear: np.ndarray,
        phi_shear: np.ndarray,
        nu: float,
    ) -> tuple[float, float, float]:
        """Calculates the variables used to for the shear deformation coefficients.

        Args:
            ixx: Second moment of area about the centroidal x-axis
            iyy: Second moment of area about the centroidal y-axis
            ixy: Second moment of area about the centroidal xy-axis
            psi_shear: Values of the psi shear function at the element nodes
            phi_shear: Values of the phi shear function at the element nodes
            nu: Effective Poisson's ratio for the cross-section

        Return:
            Shear deformation variables (``kappa_x``, ``kappa_y``, ``kappa_xy``)
        """
        # initialise properties
        kappa_x: float = 0
        kappa_y: float = 0
        kappa_xy: float = 0

        # Gauss points for 6 point Gaussian integration
        gps = gauss_points(n=6)

        for gp in gps:
            # determine shape function, shape function derivative and jacobian
            n, b, j = shape_function(coords=self.coords, gauss_point=gp)

            # determine x and y position at Gauss point
            nx = np.dot(n, np.transpose(self.coords[0, :]))
            ny = np.dot(n, np.transpose(self.coords[1, :]))

            # determine shear parameters
            r = nx**2 - ny**2
            q = 2 * nx * ny
            d1 = ixx * r - ixy * q
            d2 = ixy * r + ixx * q
            h1 = -ixy * r + iyy * q
            h2 = -iyy * r - ixy * q

            kappa_x += (
                gp[0]
                * (psi_shear.dot(np.transpose(b)) - nu / 2 * np.array([d1, d2])).dot(
                    b.dot(psi_shear) - nu / 2 * np.array([d1, d2])
                )
                * j
                * self.material.elastic_modulus
            )
            kappa_y += (
                gp[0]
                * (phi_shear.dot(np.transpose(b)) - nu / 2 * np.array([h1, h2])).dot(
                    b.dot(phi_shear) - nu / 2 * np.array([h1, h2])
                )
                * j
                * self.material.elastic_modulus
            )
            kappa_xy += (
                gp[0]
                * (psi_shear.dot(np.transpose(b)) - nu / 2 * np.array([d1, d2])).dot(
                    b.dot(phi_shear) - nu / 2 * np.array([h1, h2])
                )
                * j
                * self.material.elastic_modulus
            )

        return kappa_x, kappa_y, kappa_xy

    def monosymmetry_integrals(
        self,
        phi: float,
    ) -> tuple[float, float, float, float]:
        """Calculates the integrals used to evaluate the monosymmetry constants.

        Args:
            phi: Principal bending axis angle, in degrees

        Return:
            Integrals used to evaluate the monosymmetry constants (``int_x``, ``int_y``,
            ``int_11``, ``int_22``)
        """
        # initialise properties
        int_x: float = 0
        int_y: float = 0
        int_11: float = 0
        int_22: float = 0

        # Gauss points for 6 point Gaussian integration
        gps = gauss_points(n=6)

        for gp in gps:
            # determine shape function and jacobian
            n, _, j = shape_function(coords=self.coords, gauss_point=gp)

            # determine x and y position at Gauss point
            nx = np.dot(n, np.transpose(self.coords[0, :]))
            ny = np.dot(n, np.transpose(self.coords[1, :]))

            # determine 11 and 22 position at Gauss point
            nx_11, ny_22 = principal_coordinate(phi=phi, x=nx, y=ny)

            # weight the monosymmetry integrals by the section elastic modulus
            int_x += (
                gp[0]
                * (nx * nx * ny + ny * ny * ny)
                * j
                * self.material.elastic_modulus
            )
            int_y += (
                gp[0]
                * (ny * ny * nx + nx * nx * nx)
                * j
                * self.material.elastic_modulus
            )
            int_11 += (
                gp[0]
                * (nx_11 * nx_11 * ny_22 + ny_22 * ny_22 * ny_22)
                * j
                * self.material.elastic_modulus
            )
            int_22 += (
                gp[0]
                * (ny_22 * ny_22 * nx_11 + nx_11 * nx_11 * nx_11)
                * j
                * self.material.elastic_modulus
            )

        return int_x, int_y, int_11, int_22

    def element_stress(
        self,
        n: float,
        mxx: float,
        myy: float,
        m11: float,
        m22: float,
        mzz: float,
        vx: float,
        vy: float,
        ea: float,
        cx: float,
        cy: float,
        ixx: float,
        iyy: float,
        ixy: float,
        i11: float,
        i22: float,
        phi: float,
        j: float,
        nu: float,
        omega: np.ndarray,
        psi_shear: np.ndarray,
        phi_shear: np.ndarray,
        delta_s: float,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
    ]:
        r"""Calculates the stress within an element resulting from a specified loading.

        Args:
            n: Axial force
            mxx: Bending moment about the centroidal xx-axis
            myy: Bending moment about the centroidal yy-axis
            m11: Bending moment about the centroidal 11-axis
            m22: Bending moment about the centroidal 22-axis
            mzz: Torsion moment about the centroidal zz-axis
            vx: Shear force acting in the x-direction
            vy: Shear force acting in the y-direction
            ea: Modulus weighted area
            cx: x position of the elastic centroid
            cy: y position of the elastic centroid
            ixx: Second moment of area about the centroidal x-axis
            iyy: Second moment of area about the centroidal y-axis
            ixy: Second moment of area about the centroidal xy-axis
            i11: Second moment of area about the principal 11-axis
            i22: Second moment of area about the principal 22-axis
            phi: Principal bending axis angle
            j: St. Venant torsion constant
            nu: Effective Poisson's ratio for the cross-section
            omega: Values of the warping function at the element nodes
            psi_shear: Values of the psi shear function at the element nodes
            phi_shear: Values of the phi shear function at the element nodes
            delta_s: Cross-section shear factor

        Return:
            Tuple containing element stresses and integration weights
            (:math:`\sigma_{zz,n}`, :math:`\sigma_{zz,mxx}`,
            :math:`\sigma_{zz,myy}`, :math:`\sigma_{zz,m11}`,
            :math:`\sigma_{zz,m22}`, :math:`\sigma_{zx,mzz}`,
            :math:`\sigma_{zy,mzz}`, :math:`\sigma_{zx,vx}`,
            :math:`\sigma_{zy,vx}`, :math:`\sigma_{zx,vy}`,
            :math:`\sigma_{zy,vy}`, :math:`w_i`)
        """
        # calculate axial stress
        sig_zz_n = n * np.ones(6) * self.material.elastic_modulus / ea

        # initialise stresses at the gauss points
        sig_zz_mxx_gp = np.zeros((6, 1))
        sig_zz_myy_gp = np.zeros((6, 1))
        sig_zz_m11_gp = np.zeros((6, 1))
        sig_zz_m22_gp = np.zeros((6, 1))
        sig_zxy_mzz_gp = np.zeros((6, 2))
        sig_zxy_vx_gp = np.zeros((6, 2))
        sig_zxy_vy_gp = np.zeros((6, 2))

        # Gauss points for 6 point Gaussian integration
        gps = gauss_points(n=6)

        for i, gp in enumerate(gps):
            # determine x and y positions with respect to the centroidal axis
            coords_c = np.zeros((2, 6))
            coords_c[0, :] = self.coords[0, :] - cx
            coords_c[1, :] = self.coords[1, :] - cy

            # determine shape function, shape function derivative and jacobian
            n_shape, b, _ = shape_function(coords=coords_c, gauss_point=gp)

            # determine x and y position at Gauss point
            nx = np.dot(n_shape, np.transpose(coords_c[0, :]))
            ny = np.dot(n_shape, np.transpose(coords_c[1, :]))

            # determine 11 and 22 position at Gauss point
            nx_11, ny_22 = principal_coordinate(phi=phi, x=nx, y=ny)

            # determine shear parameters
            r = nx**2 - ny**2
            q = 2 * nx * ny
            d1 = ixx * r - ixy * q
            d2 = ixy * r + ixx * q
            h1 = -ixy * r + iyy * q
            h2 = -iyy * r - ixy * q

            # calculate element stresses
            sig_zz_mxx_gp[i, :] = self.material.elastic_modulus * (
                -(ixy * mxx) / (ixx * iyy - ixy**2) * nx
                + (iyy * mxx) / (ixx * iyy - ixy**2) * ny
            )
            sig_zz_myy_gp[i, :] = self.material.elastic_modulus * (
                -(ixx * myy) / (ixx * iyy - ixy**2) * nx
                + (ixy * myy) / (ixx * iyy - ixy**2) * ny
            )
            sig_zz_m11_gp[i, :] = self.material.elastic_modulus * m11 / i11 * ny_22
            sig_zz_m22_gp[i, :] = self.material.elastic_modulus * -m22 / i22 * nx_11

            if mzz != 0:
                sig_zxy_mzz_gp[i, :] = (
                    self.material.elastic_modulus
                    * mzz
                    / j
                    * (b.dot(omega) - np.array([ny, -nx]))
                )

            if vx != 0:
                sig_zxy_vx_gp[i, :] = (
                    self.material.elastic_modulus
                    * vx
                    / delta_s
                    * (b.dot(psi_shear) - nu / 2 * np.array([d1, d2]))
                )

            if vy != 0:
                sig_zxy_vy_gp[i, :] = (
                    self.material.elastic_modulus
                    * vy
                    / delta_s
                    * (b.dot(phi_shear) - nu / 2 * np.array([h1, h2]))
                )

        # extrapolate results to nodes
        sig_zz_mxx = extrapolate_to_nodes(w=sig_zz_mxx_gp[:, 0])
        sig_zz_myy = extrapolate_to_nodes(w=sig_zz_myy_gp[:, 0])
        sig_zz_m11 = extrapolate_to_nodes(w=sig_zz_m11_gp[:, 0])
        sig_zz_m22 = extrapolate_to_nodes(w=sig_zz_m22_gp[:, 0])
        sig_zx_mzz = extrapolate_to_nodes(w=sig_zxy_mzz_gp[:, 0])
        sig_zy_mzz = extrapolate_to_nodes(w=sig_zxy_mzz_gp[:, 1])
        sig_zx_vx = extrapolate_to_nodes(w=sig_zxy_vx_gp[:, 0])
        sig_zy_vx = extrapolate_to_nodes(w=sig_zxy_vx_gp[:, 1])
        sig_zx_vy = extrapolate_to_nodes(w=sig_zxy_vy_gp[:, 0])
        sig_zy_vy = extrapolate_to_nodes(w=sig_zxy_vy_gp[:, 1])

        return (
            sig_zz_n,
            sig_zz_mxx,
            sig_zz_myy,
            sig_zz_m11,
            sig_zz_m22,
            sig_zx_mzz,
            sig_zy_mzz,
            sig_zx_vx,
            sig_zy_vx,
            sig_zx_vy,
            sig_zy_vy,
            gps[:, 0],
        )

    def local_element_stress(
        self,
        p: tuple[float, float],
        n: float,
        mxx: float,
        myy: float,
        m11: float,
        m22: float,
        mzz: float,
        vx: float,
        vy: float,
        ea: float,
        cx: float,
        cy: float,
        ixx: float,
        iyy: float,
        ixy: float,
        i11: float,
        i22: float,
        phi: float,
        j: float,
        nu: float,
        omega: np.ndarray,
        psi_shear: np.ndarray,
        phi_shear: np.ndarray,
        delta_s: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        r"""Calculates the stress at a point resulting from a specified loading.

        Args:
            p: Point (``x``, ``y``) in the global coordinate system that is within the
                element
            n: Axial force
            mxx: Bending moment about the centroidal xx-axis
            myy: Bending moment about the centroidal yy-axis
            m11: Bending moment about the centroidal 11-axis
            m22: Bending moment about the centroidal 22-axis
            mzz: Torsion moment about the centroidal zz-axis
            vx: Shear force acting in the x-direction
            vy: Shear force acting in the y-direction
            ea: Modulus weighted area
            cx: x position of the elastic centroid
            cy: y position of the elastic centroid
            ixx: Second moment of area about the centroidal x-axis
            iyy: Second moment of area about the centroidal y-axis
            ixy: Second moment of area about the centroidal xy-axis
            i11: Second moment of area about the principal 11-axis
            i22: Second moment of area about the principal 22-axis
            phi: Principal bending axis angle
            j: St. Venant torsion constant
            nu: Effective Poisson's ratio for the cross-section
            omega: Values of the warping function at the element nodes
            psi_shear: Values of the psi shear function at the element nodes
            phi_shear: Values of the phi shear function at the element nodes
            delta_s: Cross-section shear factor

        Return:
            Tuple containing stress values at point ``p`` (:math:`\sigma_{zz}`,
            :math:`\sigma_{zx}`, :math:`\sigma_{zy}`)
        """
        # get the elements nodal stress
        (
            sig_zz_n_el,
            sig_zz_mxx_el,
            sig_zz_myy_el,
            sig_zz_m11_el,
            sig_zz_m22_el,
            sig_zx_mzz_el,
            sig_zy_mzz_el,
            sig_zx_vx_el,
            sig_zy_vx_el,
            sig_zx_vy_el,
            sig_zy_vy_el,
            _,
        ) = self.element_stress(
            n=n,
            mxx=mxx,
            myy=myy,
            m11=m11,
            m22=m22,
            mzz=mzz,
            vx=vx,
            vy=vy,
            ea=ea,
            cx=cx,
            cy=cy,
            ixx=ixx,
            iyy=iyy,
            ixy=ixy,
            i11=i11,
            i22=i22,
            phi=phi,
            j=j,
            nu=nu,
            omega=omega,
            psi_shear=psi_shear,
            phi_shear=phi_shear,
            delta_s=delta_s,
        )

        # get the local coordinates of the point within the reference element
        p_local = self.local_coord(p=p)

        # get the value of the basis functions at p_local
        n_shape = shape_function_only(p=p_local)

        # interpolate the nodal values to p_local and add the results
        (
            sig_zz_n_p,
            sig_zz_mxx_p,
            sig_zz_myy_p,
            sig_zz_m11_p,
            sig_zz_m22_p,
            sig_zx_mzz_p,
            sig_zy_mzz_p,
            sig_zx_vx_p,
            sig_zy_vx_p,
            sig_zx_vy_p,
            sig_zy_vy_p,
        ) = np.dot(
            np.array(
                [
                    sig_zz_n_el,
                    sig_zz_mxx_el,
                    sig_zz_myy_el,
                    sig_zz_m11_el,
                    sig_zz_m22_el,
                    sig_zx_mzz_el,
                    sig_zy_mzz_el,
                    sig_zx_vx_el,
                    sig_zy_vx_el,
                    sig_zx_vy_el,
                    sig_zy_vy_el,
                ]
            ),
            n_shape,
        )
        sig_zz_m_p = sig_zz_mxx_p + sig_zz_myy_p + sig_zz_m11_p + sig_zz_m22_p
        sig_zx_v_p = sig_zx_vx_p + sig_zx_vy_p
        sig_zy_v_p = sig_zy_vx_p + sig_zy_vy_p
        sig_zy_p = sig_zy_mzz_p + sig_zy_v_p
        sig_zz_p = sig_zz_n_p + sig_zz_m_p
        sig_zx_p = sig_zx_mzz_p + sig_zx_v_p
        sig_zy_p = sig_zy_mzz_p + sig_zy_v_p

        return (
            sig_zz_p,
            sig_zx_p,
            sig_zy_p,
        )

    def point_within_element(
        self,
        pt: tuple[float, float],
    ) -> bool:
        """Determines whether a point lies within the current element.

        Args:
            pt: Point to check (``x``, ``y``)

        Return:
            Whether the point lies within an element
        """
        px = pt[0]
        py = pt[1]

        # get coordinates of corner points
        x1: float = self.coords[0][0]
        y1: float = self.coords[1][0]
        x2: float = self.coords[0][1]
        y2: float = self.coords[1][1]
        x3: float = self.coords[0][2]
        y3: float = self.coords[1][2]

        # compute variables alpha, beta and gamma
        alpha = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / (
            (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        )
        beta = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / (
            (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        )
        gamma = 1.0 - alpha - beta

        # if the point lies within an element
        if alpha >= 0 and beta >= 0 and gamma >= 0:
            return True
        else:
            return False

    def local_coord(
        self,
        p: tuple[float, float],
    ) -> tuple[float, float, float]:
        """Maps a global point onto a local point.

        Args:
            p: Global coordinate (``x``, ``y``)

        Return:
            Point in local coordinates (``eta``, ``xi``, ``zeta``)
        """
        eta, xi = np.dot(self._m, p - self._x0)
        zeta = 1 - eta - xi
        return eta, xi, zeta


def gauss_points(n: int) -> np.ndarray:
    """Gaussian weights and locations for ``n`` point Gaussian integration of a Tri6.

    Args:
        n: Number of Gauss points (1, 3 or 6)

    Return:
        An ``n x 4`` matrix consisting of the integration weight and the ``eta``, ``xi``
        and ``zeta`` locations for ``n`` Gauss points
    """
    if n == 1:
        # one point gaussian integration
        return np.array([[1.0, 1.0 / 3, 1.0 / 3, 1.0 / 3]], dtype=float)

    elif n == 3:
        # three point gaussian integration
        return np.array(
            [
                [1.0 / 3, 2.0 / 3, 1.0 / 6, 1.0 / 6],
                [1.0 / 3, 1.0 / 6, 2.0 / 3, 1.0 / 6],
                [1.0 / 3, 1.0 / 6, 1.0 / 6, 2.0 / 3],
            ],
            dtype=float,
        )
    elif n == 6:
        # six point gaussian integration
        g1 = 1.0 / 18 * (8 - np.sqrt(10) + np.sqrt(38 - 44 * np.sqrt(2.0 / 5)))
        g2 = 1.0 / 18 * (8 - np.sqrt(10) - np.sqrt(38 - 44 * np.sqrt(2.0 / 5)))
        w1 = (620 + np.sqrt(213125 - 53320 * np.sqrt(10))) / 3720
        w2 = (620 - np.sqrt(213125 - 53320 * np.sqrt(10))) / 3720

        return np.array(
            [
                [w2, 1 - 2 * g2, g2, g2],
                [w2, g2, 1 - 2 * g2, g2],
                [w2, g2, g2, 1 - 2 * g2],
                [w1, g1, g1, 1 - 2 * g1],
                [w1, 1 - 2 * g1, g1, g1],
                [w1, g1, 1 - 2 * g1, g1],
            ],
            dtype=float,
        )
    else:
        raise ValueError("n must be 1, 3 or 6.")


def shape_function(
    coords: np.ndarray,
    gauss_point: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray, float]:
    """Calculates shape functions, derivates and the Jacobian determinant.

    Computes the shape functions, shape function derivatives and the determinant of the
    Jacobian matrix for a ``Tri6`` element at a given Gauss point.

    Args:
        coords: Global coordinates of the quadratic triangle vertices, of size
            ``[2 x 6]``
        gauss_point: Gaussian weight and isoparametric location of the Gauss point

    Return:
        The value of the shape functions ``N(i)`` at the given Gauss point
        (``[1 x 6]``), the derivative of the shape functions in the *j-th* global
        direction ``B(i,j)`` (``[2 x 6]``) and the determinant of the Jacobian
        matrix ``j``
    """
    # location of isoparametric co-ordinates for each Gauss point
    eta = gauss_point[1]
    xi = gauss_point[2]
    zeta = gauss_point[3]

    # value of the shape functions
    n = np.array(
        [
            eta * (2 * eta - 1),
            xi * (2 * xi - 1),
            zeta * (2 * zeta - 1),
            4 * eta * xi,
            4 * xi * zeta,
            4 * eta * zeta,
        ],
        dtype=float,
    )

    # derivatives of the shape functions wrt the isoparametric co-ordinates
    b_iso = np.array(
        [
            [4 * eta - 1, 0, 0, 4 * xi, 0, 4 * zeta],
            [0, 4 * xi - 1, 0, 4 * eta, 4 * zeta, 0],
            [0, 0, 4 * zeta - 1, 0, 4 * xi, 4 * eta],
        ],
        dtype=float,
    )

    # form Jacobian matrix
    j_upper = np.array([[1, 1, 1]])
    j_lower = np.dot(coords, np.transpose(b_iso))
    j = np.vstack((j_upper, j_lower))

    # calculate the jacobian
    jacobian = 0.5 * np.linalg.det(j)

    # if the area of the element is not zero
    if jacobian != 0:
        # calculate the p matrix
        p = np.dot(np.linalg.inv(j), np.array([[0, 0], [1, 0], [0, 1]]))

        # calculate the b matrix in terms of cartesian co-ordinates
        b = np.transpose(np.dot(np.transpose(b_iso), p))
    else:
        b = np.zeros((2, 6))  # empty b matrix

    return n, b, jacobian


def shape_function_only(p: tuple[float, float, float]) -> np.ndarray:
    """The values of the ``Tri6`` shape function at a point ``p``.

    Args:
        p: Point (``eta``, ``xi``, ``zeta``) in the local coordinate system.

    Return:
        The shape function values at ``p``, of size ``[1 x 6]``
    """
    eta = p[0]
    xi = p[1]
    zeta = p[2]

    return np.array(
        [
            eta * (2 * eta - 1),
            xi * (2 * xi - 1),
            zeta * (2 * zeta - 1),
            4 * eta * xi,
            4 * xi * zeta,
            4 * eta * zeta,
        ]
    )


def extrapolate_to_nodes(w: np.ndarray) -> np.ndarray:
    """Extrapolates results at six Gauss points to the six nodes of a ``Tri6`` element.

    Args:
        w: Results at the six Gauss points, of size ``[1 x 6]``

    Return:
        Extrapolated nodal values at the six nodes, of size ``[1 x 6]``
    """
    h_inv = np.array(
        [
            [
                1.87365927351160,
                0.138559587411935,
                0.138559587411935,
                -0.638559587411936,
                0.126340726488397,
                -0.638559587411935,
            ],
            [
                0.138559587411935,
                1.87365927351160,
                0.138559587411935,
                -0.638559587411935,
                -0.638559587411935,
                0.126340726488397,
            ],
            [
                0.138559587411935,
                0.138559587411935,
                1.87365927351160,
                0.126340726488396,
                -0.638559587411935,
                -0.638559587411935,
            ],
            [
                0.0749010751157440,
                0.0749010751157440,
                0.180053080734478,
                1.36051633430762,
                -0.345185782636792,
                -0.345185782636792,
            ],
            [
                0.180053080734478,
                0.0749010751157440,
                0.0749010751157440,
                -0.345185782636792,
                1.36051633430762,
                -0.345185782636792,
            ],
            [
                0.0749010751157440,
                0.180053080734478,
                0.0749010751157440,
                -0.345185782636792,
                -0.345185782636792,
                1.36051633430762,
            ],
        ]
    )

    return h_inv.dot(w)


def principal_coordinate(
    phi: float,
    x: float,
    y: float,
) -> tuple[float, float]:
    """Converts global coordinates to principal coordinates.

    Args:
        phi: Principal bending axis angle, in degrees
        x: x-coordinate in the global coordinate system
        y: y-coordinate in the global coordinate system

    Return:
        Principal axis coordinates (``x11``, ``y22``)
    """
    cos_phi = np.cos(phi)
    sin_phi = np.sin(phi)

    return x * cos_phi + y * sin_phi, y * cos_phi - x * sin_phi


def global_coordinate(
    phi: float,
    x11: float,
    y22: float,
) -> tuple[float, float]:
    """Converts prinicpal coordinates to global coordinates.

    Args:
        phi: Principal bending axis angle, in degrees
        x11: 11-coordinate in the principal coorindate system
        y22: 22-coordinate in the principal coorindate system

    Return:
        Global axis coordinates (``x``, ``y``)
    """
    cos_phi = np.cos(phi)
    sin_phi = np.sin(phi)

    return x11 * cos_phi - y22 * sin_phi, x11 * sin_phi + y22 * cos_phi


def point_above_line(
    u: np.ndarray,
    px: float,
    py: float,
    x: float,
    y: float,
) -> bool:
    """Determines whether a point is a above or below a line.

    Args:
        u: Unit vector parallel to the line, of size ``[1 x 2]``
        px: x-coordinate of a point on the line
        py: y-coordinate of a point on the line
        x: x-coordinate of the point to be tested
        y: y-coordinate of the point to be tested

    Return:
        Returns True if the point is above the line or False*if the point is below the
            line
    """
    # vector from point to point on line
    pq = np.array([px - x, py - y])
    return bool(np.cross(pq, u) > 0)
