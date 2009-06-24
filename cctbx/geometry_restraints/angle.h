#ifndef CCTBX_GEOMETRY_RESTRAINTS_ANGLE_H
#define CCTBX_GEOMETRY_RESTRAINTS_ANGLE_H

#include <cctbx/sgtbx/rt_mx.h>
#include <cctbx/geometry_restraints/utils.h>
#include <scitbx/constants.h>
#include <scitbx/optional_copy.h>

namespace cctbx { namespace geometry_restraints {

  //! Grouping of indices into array of sites (i_seqs) and angle_params.
  struct angle_proxy
  {
    //! Support for shared_proxy_select.
    typedef af::tiny<unsigned, 3> i_seqs_type;

    //! Default constructor. Some data members are not initialized!
    angle_proxy() {}

    //! Constructor.
    angle_proxy(
      i_seqs_type const& i_seqs_,
      double angle_ideal_,
      double weight_)
    :
      i_seqs(i_seqs_),
      angle_ideal(angle_ideal_),
      weight(weight_)
    {}

    //! Constructor.
    angle_proxy(
      i_seqs_type const& i_seqs_,
      af::shared<sgtbx::rt_mx> const& sym_ops_,
      double angle_ideal_,
      double weight_)
    :
      i_seqs(i_seqs_),
      sym_ops(sym_ops_),
      angle_ideal(angle_ideal_),
      weight(weight_)
    {
      if ( sym_ops.get() ) {
        CCTBX_ASSERT(sym_ops.get()->size() == i_seqs.size());
      }
    }

    //! Constructor.
    /*! Not available in Python.
     */
    angle_proxy(
      i_seqs_type const& i_seqs_,
      angle_proxy const& proxy)
    :
      i_seqs(i_seqs_),
      angle_ideal(proxy.angle_ideal),
      weight(proxy.weight)
    {}

    //! Constructor.
    /*! Not available in Python.
     */
    angle_proxy(
      i_seqs_type const& i_seqs_,
      af::shared<sgtbx::rt_mx> const& sym_ops_,
      angle_proxy const& proxy)
    :
      i_seqs(i_seqs_),
      sym_ops(sym_ops_),
      angle_ideal(proxy.angle_ideal),
      weight(proxy.weight)
    {}

    //! Sorts i_seqs such that i_seq[0] < i_seq[2].
    angle_proxy
    sort_i_seqs() const
    {
      angle_proxy result(*this);
      if (result.i_seqs[0] > result.i_seqs[2]) {
        std::swap(result.i_seqs[0], result.i_seqs[2]);
        if ( sym_ops.get() ) {
          std::swap(result.sym_ops[0], result.sym_ops[2]);
        }
      }
      return result;
    }

    //! Indices into array of sites.
    i_seqs_type i_seqs;
    //! Optional array of symmetry operations.
    scitbx::optional_copy<af::shared<sgtbx::rt_mx> > sym_ops;
    //! Parameter.
    double angle_ideal;
    //! Parameter.
    double weight;
  };

  //! Residual and gradient calculations for angle restraint.
  class angle
  {
    public:
      //! Default constructor. Some data members are not initialized!
      angle() {}

      //! Constructor.
      angle(
        af::tiny<scitbx::vec3<double>, 3> const& sites_,
        double angle_ideal_,
        double weight_)
      :
        sites(sites_),
        angle_ideal(angle_ideal_),
        weight(weight_)
      {
        init_angle_model();
      }

      /*! \brief Coordinates are copied from sites_cart according to
          proxy.i_seqs, parameters are copied from proxy.
          This constructor ignores any symmetry operations and assumes
          all i_seqs to be in the asymmetric unit.
       */
      angle(
        af::const_ref<scitbx::vec3<double> > const& sites_cart,
        angle_proxy const& proxy)
      :
        angle_ideal(proxy.angle_ideal),
        weight(proxy.weight)
      {
        for(int i=0;i<3;i++) {
          std::size_t i_seq = proxy.i_seqs[i];
          CCTBX_ASSERT(i_seq < sites_cart.size());
          sites[i] = sites_cart[i_seq];
        }
        init_angle_model();
      }

      /*! \brief Coordinates are obtained from sites_cart according
          to proxy.i_seqs by applying proxy.sym_ops and unit_cell,
          parameters are copied from proxy.
       */
      angle(
        uctbx::unit_cell const& unit_cell,
        af::const_ref<scitbx::vec3<double> > const& sites_cart,
        angle_proxy const& proxy)
      :
        angle_ideal(proxy.angle_ideal),
        weight(proxy.weight)
      {
        for(int i=0;i<3;i++) {
          std::size_t i_seq = proxy.i_seqs[i];
          CCTBX_ASSERT(i_seq < sites_cart.size());
          sites[i] = sites_cart[i_seq];
          if ( proxy.sym_ops.get() ) {
            sgtbx::rt_mx rt_mx = proxy.sym_ops[i];
            if ( !rt_mx.is_unit_mx() ) {
              sites[i] = unit_cell.orthogonalize(
                rt_mx * unit_cell.fractionalize(sites[i]));
            }
          }
        }
        init_angle_model();
      }

      //! weight * delta**2.
      /*! See also: Hendrickson, W.A. (1985). Meth. Enzym. 115, 252-270.
       */
      double
      residual() const { return weight * scitbx::fn::pow2(delta); }

      //! Gradients with respect to the three sites.
      /*! The formula for the gradients is singular at delta = 0
          and delta = 180. However, the gradients converge to zero
          near these singularities. To avoid numerical problems, the
          gradients are set to zero exactly if the intermediate
          result sqrt(1-cos(angle_model)**2) < epsilon.

          See also:
            http://salilab.org/modeller/manual/manual.html,
            "Features and their derivatives"
       */
      af::tiny<scitbx::vec3<double>, 3>
      gradients(double epsilon=1.e-100) const
      {
        af::tiny<scitbx::vec3<double>, 3> result;
        if (!have_angle_model) {
          result.fill(scitbx::vec3<double>(0,0,0));
        }
        else {
          double
          sin_angle_model = std::sqrt(1-scitbx::fn::pow2(cos_angle_model));
          if (sin_angle_model < epsilon) {
            result.fill(scitbx::vec3<double>(0,0,0));
          }
          else {
            using scitbx::constants::pi_180;
            scitbx::vec3<double>
                d_angle_d_site0, d_angle_d_site1, d_angle_d_site2;
            double grad_factor = -2 * weight * delta / pi_180;
            d_angle_d_site0 = (d_01_unit * cos_angle_model - d_21_unit) /
                              (sin_angle_model * d_01_abs);
            result[0] = grad_factor * d_angle_d_site0;
            d_angle_d_site2 = (d_21_unit * cos_angle_model - d_01_unit) /
                              (sin_angle_model * d_21_abs);
            result[2] = grad_factor * d_angle_d_site2;
            result[1] = -(result[0] + result[2]);
            bool do_curv(false);
            if (do_curv)
            {
              af::tiny<scitbx::vec3<double>, 3> curvatures;
              d_angle_d_site1 = result[1] / grad_factor;
              scitbx::vec3<double> v111(1,1,1);
              double sinsqr = scitbx::fn::pow2(sin_angle_model);

              scitbx::vec3<double> d2_angle_d_site00 =
                 (2. * d_21_unit.each_mul(d_01_unit) +
                 cos_angle_model * (v111 * sinsqr - d_21_unit.each_mul(d_21_unit)
                 - (1. + 2. * sinsqr) * d_01_unit.each_mul(d_01_unit))) /
                 (scitbx::fn::pow2(d_01_abs)*sin_angle_model*sinsqr);

              scitbx::vec3<double> d2_angle_d_site22 =
                 (2. * d_01_unit.each_mul(d_21_unit) +
                 cos_angle_model * (v111 * sinsqr - d_01_unit.each_mul(d_01_unit)
                 - (1. + 2. * sinsqr) * d_21_unit.each_mul(d_21_unit))) /
                 (scitbx::fn::pow2(d_21_abs)*sin_angle_model*sinsqr);

               double d01sqr = scitbx::fn::pow2(d_01_abs);
               double d21sqr = scitbx::fn::pow2(d_21_abs);
               scitbx::vec3<double> term1 = d_angle_d_site1 / sin_angle_model;
               scitbx::vec3<double> tvec1 = d_01_abs * d_21_unit;
               scitbx::vec3<double> tvec2 = d_21_abs * d_01_unit;
               scitbx::vec3<double> sumvec = d_01 + d_21;
               scitbx::vec3<double> d2_angle_d_site11 =
                 (-2. * cos_angle_model *
                 (tvec1.each_mul(tvec1) + tvec2.each_mul(tvec2)) +
                 (tvec1+tvec2).each_mul(sumvec) +
                 (d01sqr + d21sqr) * v111 * cos_angle_model +
                 (d01sqr * d_21 + d21sqr * d_01).each_mul(term1) -
                 d_01_abs * d_21_abs *
                 (2. * v111 + cos_angle_model * term1.each_mul(sumvec))) /
                 (sin_angle_model * d01sqr * d21sqr);

               double curvfac = 2. * weight / pi_180;
               curvatures[0] = curvfac *
                 (d_angle_d_site0.each_mul(d_angle_d_site0) / pi_180 -
                 delta * d2_angle_d_site00);
               curvatures[1] = curvfac *
                 (d_angle_d_site1.each_mul(d_angle_d_site1) / pi_180 -
                 delta * d2_angle_d_site11);
               curvatures[2] = curvfac *
                 (d_angle_d_site2.each_mul(d_angle_d_site2) / pi_180 -
                 delta * d2_angle_d_site22);
            }
          }
        }
        return result;
      }

      //! Support for angle_residual_sum.
      /*! Not available in Python.
       */
      void
      add_gradients(
        af::ref<scitbx::vec3<double> > const& gradient_array,
        angle_proxy::i_seqs_type const& i_seqs) const
      {
        af::tiny<scitbx::vec3<double>, 3> grads = gradients();
        for(int i=0;i<3;i++) {
          gradient_array[i_seqs[i]] += grads[i];
        }
      }

      //! Support for angle_residual_sum.
      /*! Not available in Python.

          Inefficient implementation, r_inv_cart is not cached.
          TODO: use asu_mappings to take advantage of caching of r_inv_cart.
       */
      void
      add_gradients(
        uctbx::unit_cell const& unit_cell,
        af::ref<scitbx::vec3<double> > const& gradient_array,
        angle_proxy const& proxy) const
      {
        angle_proxy::i_seqs_type const& i_seqs = proxy.i_seqs;
        scitbx::optional_copy<af::shared<sgtbx::rt_mx> > const& sym_ops = proxy.sym_ops;
        af::tiny<scitbx::vec3<double>, 3> grads = gradients();
        for(int i=0;i<3;i++) {
          if ( sym_ops.get() && !sym_ops[i].is_unit_mx() ) {
            scitbx::mat3<double> r_inv_cart_ = r_inv_cart(unit_cell, sym_ops[i]);
            gradient_array[i_seqs[i]] += grads[i] * r_inv_cart_;
          }
          else { gradient_array[i_seqs[i]] += grads[i]; }
        }
      }

      //! Cartesian coordinates of sites forming the angle.
      af::tiny<scitbx::vec3<double>, 3> sites;
      //! Parameter (usually as passed to the constructor).
      double angle_ideal;
      //! Parameter (usually as passed to the constructor).
      double weight;
      //! false in singular situations.
      bool have_angle_model;
    protected:
      double d_01_abs;
      double d_21_abs;
      scitbx::vec3<double> d_01;
      scitbx::vec3<double> d_21;
      scitbx::vec3<double> d_01_unit;
      scitbx::vec3<double> d_21_unit;
      double cos_angle_model;
    public:
      //! Value of angle formed by the sites.
      double angle_model;
      /*! \brief Smallest difference between angle_model and angle_ideal
          taking the periodicity into account.
       */
      /*! See also: angle_delta_deg
       */
      double delta;

    protected:
      void
      init_angle_model()
      {
        have_angle_model = false;
        d_01_abs = 0;
        d_21_abs = 0;
        d_01.fill(0);
        d_21.fill(0);
        d_01_unit.fill(0);
        d_21_unit.fill(0);
        cos_angle_model = -9;
        angle_model = angle_ideal;
        delta = 0;
        d_01 = sites[0] - sites[1];
        d_01_abs = d_01.length();
        if (d_01_abs > 0) {
          d_21 = sites[2] - sites[1];
          d_21_abs = d_21.length();
          if (d_21_abs > 0) {
            d_01_unit = d_01 / d_01_abs;
            d_21_unit = d_21 / d_21_abs;
            cos_angle_model = std::max(-1.,std::min(1.,d_01_unit*d_21_unit));
            angle_model = std::acos(cos_angle_model)
                        / scitbx::constants::pi_180;
            have_angle_model = true;
            delta = angle_delta_deg(angle_model, angle_ideal);
          }
        }
      }
  };

  /*! Fast computation of angle::delta given an array of angle proxies,
      ignoring proxy.sym_ops.
   */
  inline
  af::shared<double>
  angle_deltas(
    af::const_ref<scitbx::vec3<double> > const& sites_cart,
    af::const_ref<angle_proxy> const& proxies)
  {
    return detail::generic_deltas<angle_proxy, angle>::get(
      sites_cart, proxies);
  }

  /*! Fast computation of angle::delta given an array of angle proxies.
      taking into account proxy.sym_ops.
   */
  inline
  af::shared<double>
  angle_deltas(
    uctbx::unit_cell const& unit_cell,
    af::const_ref<scitbx::vec3<double> > const& sites_cart,
    af::const_ref<angle_proxy> const& proxies)
  {
    return detail::generic_deltas<angle_proxy, angle>::get(
      unit_cell, sites_cart, proxies);
  }

  /*! Fast computation of angle::residual() given an array of angle proxies,
      ignoring proxy.sym_ops.
   */
  inline
  af::shared<double>
  angle_residuals(
    af::const_ref<scitbx::vec3<double> > const& sites_cart,
    af::const_ref<angle_proxy> const& proxies)
  {
    return detail::generic_residuals<angle_proxy, angle>::get(
      sites_cart, proxies);
  }

  /*! Fast computation of angle::residual() given an array of angle proxies,
      taking account of proxy.sym_ops.
   */
  inline
  af::shared<double>
  angle_residuals(
    uctbx::unit_cell const& unit_cell,
    af::const_ref<scitbx::vec3<double> > const& sites_cart,
    af::const_ref<angle_proxy> const& proxies)
  {
    return detail::generic_residuals<angle_proxy, angle>::get(
      unit_cell, sites_cart, proxies);
  }

  /*! Fast computation of sum of angle::residual() and gradients
      given an array of angle proxies, ignoring proxy.sym_ops.
   */
  /*! The angle::gradients() are added to the gradient_array if
      gradient_array.size() == sites_cart.size().
      gradient_array must be initialized before this function
      is called.
      No gradient calculations are performed if gradient_array.size() == 0.
   */
  inline
  double
  angle_residual_sum(
    af::const_ref<scitbx::vec3<double> > const& sites_cart,
    af::const_ref<angle_proxy> const& proxies,
    af::ref<scitbx::vec3<double> > const& gradient_array)
  {
    return detail::generic_residual_sum<angle_proxy, angle>::get(
      sites_cart, proxies, gradient_array);
  }

  /*! Fast computation of sum of angle::residual() and gradients
      given an array of angle proxies, taking into account proxy.sym_ops.
   */
  /*! The angle::gradients() are added to the gradient_array if
      gradient_array.size() == sites_cart.size().
      gradient_array must be initialized before this function
      is called.
      No gradient calculations are performed if gradient_array.size() == 0.
   */
  inline
  double
  angle_residual_sum(
    uctbx::unit_cell const& unit_cell,
    af::const_ref<scitbx::vec3<double> > const& sites_cart,
    af::const_ref<angle_proxy> const& proxies,
    af::ref<scitbx::vec3<double> > const& gradient_array)
  {
    return detail::generic_residual_sum<angle_proxy, angle>::get(
      unit_cell, sites_cart, proxies, gradient_array);
  }

}} // namespace cctbx::geometry_restraints

#endif // CCTBX_GEOMETRY_RESTRAINTS_ANGLE_H
